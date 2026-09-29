"""Persistence use cases called by internal n8n endpoints and the review portal."""

import base64
import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from invoiceops.config import get_settings
from invoiceops.domain import (
    may_post,
    money,
    required_approval_roles,
    resolve_vendor,
    validate_document,
)
from invoiceops.models import (
    AccountingMapping,
    Approval,
    ApprovalPolicy,
    BusinessException,
    DigestRun,
    DocumentJob,
    Finding,
    IntakeEvent,
    Invoice,
    InvoiceVersion,
    LineItem,
    PostingOperation,
    PurchaseOrder,
    Receipt,
    SimulatedBill,
    SourceFile,
    TimelineEvent,
    Vendor,
    Workspace,
    as_utc,
    now,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode())


def add_timeline(db: Session, invoice: Invoice, event: str, detail: str) -> None:
    db.add(
        TimelineEvent(
            workspace_id=invoice.workspace_id,
            invoice_id=invoice.id,
            event=event,
            detail=detail[:500],
        )
    )


def get_invoice(
    db: Session, invoice_id: str, workspace_id: str | None = None, *, lock: bool = False
) -> Invoice:
    statement = select(Invoice).where(Invoice.id == invoice_id)
    if workspace_id:
        statement = statement.where(Invoice.workspace_id == workspace_id)
    if lock:
        statement = statement.with_for_update()
    invoice = db.scalar(statement)
    if invoice is None:
        raise HTTPException(404, "Invoice not found")
    return invoice


def receive_event(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    workspace_id = str(payload.get("workspace_id", ""))
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(404, "Workspace not found")
    source_system = str(payload.get("source_system", ""))
    source_id = str(payload.get("source_id", ""))
    if source_system not in {"replay", "imap", "drive"} or not source_id or len(source_id) > 150:
        raise HTTPException(422, "Invalid source identity")
    raw_b64 = payload.get("content_base64")
    if not isinstance(raw_b64, str):
        raise HTTPException(422, "content_base64 is required")
    try:
        content = base64.b64decode(raw_b64, validate=True)
    except ValueError as exc:
        raise HTTPException(422, "Invalid base64 content") from exc
    if not content or len(content) > settings.max_document_bytes:
        raise HTTPException(413, "File is empty or exceeds the 8 MB limit")
    mime_type = str(payload.get("mime_type", ""))
    filename = str(payload.get("filename", ""))
    if mime_type == "application/pdf" and content.startswith(b"%PDF-"):
        suffix = ".pdf"
    elif mime_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif mime_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    else:
        raise HTTPException(415, "Only valid PDF, PNG and JPEG invoices are accepted")
    source_key = f"{source_system}:{source_id}"
    content_hash = sha256(content)
    payload_hash = canonical_hash(
        {"source_key": source_key, "filename": filename, "content_hash": content_hash}
    )
    previous = db.scalar(
        select(IntakeEvent).where(
            IntakeEvent.workspace_id == workspace_id, IntakeEvent.source_id == source_key
        )
    )
    if previous:
        if previous.payload_hash != payload_hash:
            raise HTTPException(409, "Source ID was redelivered with conflicting content")
        return {
            "invoice_id": previous.invoice_id,
            "duplicate": True,
            "source_hash": content_hash,
            "source_file_id": previous.source_file_id,
        }
    revision_of = payload.get("revision_of")
    revision_target = None
    if revision_of:
        revision_target = get_invoice(db, str(revision_of), workspace_id, lock=True)
        has_posting = db.scalar(
            select(PostingOperation.id)
            .where(PostingOperation.invoice_id == revision_target.id)
            .limit(1)
        )
        if revision_target.accounting_id or has_posting:
            raise HTTPException(409, "A posting operation prevents document revision")
    source = db.scalar(
        select(SourceFile).where(
            SourceFile.workspace_id == workspace_id, SourceFile.content_hash == content_hash
        )
    )
    if source is None:
        path = settings.data_dir / "uploads" / workspace_id / f"{content_hash}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        source = SourceFile(
            id=str(uuid4()),
            workspace_id=workspace_id,
            path=str(path),
            mime_type=mime_type,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        db.add(source)
        db.flush()
    previous_invoice = db.scalar(
        select(Invoice)
        .where(Invoice.workspace_id == workspace_id, Invoice.source_file_id == source.id)
        .order_by(Invoice.created_at.asc())
    )
    duplicate = previous_invoice is not None
    invoice = previous_invoice
    if revision_target:
        invoice = revision_target
        invoice.source_file_id = source.id
        invoice.status = "received"
        duplicate = False
    if invoice is None:
        invoice = Invoice(
            id=str(uuid4()), workspace_id=workspace_id, source_file_id=source.id, status="received"
        )
        db.add(invoice)
        db.flush()
        add_timeline(db, invoice, "received", f"{source_system} source {source_id} accepted")
    event = IntakeEvent(
        id=str(uuid4()),
        workspace_id=workspace_id,
        source_id=source_key,
        payload_hash=payload_hash,
        source_file_id=source.id,
        invoice_id=invoice.id,
        duplicate=duplicate,
    )
    db.add(event)
    db.commit()
    return {
        "invoice_id": invoice.id,
        "duplicate": duplicate,
        "source_hash": content_hash,
        "source_file_id": source.id,
    }


def submit_job(db: Session, invoice_id: str) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, lock=True)
    existing = db.scalar(
        select(DocumentJob)
        .where(
            DocumentJob.invoice_id == invoice_id,
            DocumentJob.source_file_id == invoice.source_file_id,
            DocumentJob.status.in_(["queued", "running", "completed", "review"]),
        )
        .order_by(DocumentJob.created_at.desc())
    )
    if existing and invoice.current_version > 0:
        return {"job_id": existing.id, "status": existing.status}
    if existing and existing.status in {"queued", "running"}:
        return {"job_id": existing.id, "status": existing.status}
    job = DocumentJob(
        workspace_id=invoice.workspace_id,
        invoice_id=invoice.id,
        source_file_id=invoice.source_file_id,
        status="queued",
    )
    db.add(job)
    invoice.status = "extracting"
    add_timeline(db, invoice, "extracting", "Document job queued")
    db.commit()
    return {"job_id": job.id, "status": "queued"}


def _vendor_candidates(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    vendors = db.scalars(select(Vendor).where(Vendor.workspace_id == workspace_id)).all()
    return [{"id": v.id, "name": v.name, "aliases": v.aliases} for v in vendors]


def validate_invoice(db: Session, invoice_id: str, job_id: str) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, lock=True)
    job = db.get(DocumentJob, job_id)
    if job is None or job.invoice_id != invoice.id or job.workspace_id != invoice.workspace_id:
        raise HTTPException(404, "Document job not found")
    if job.source_file_id != invoice.source_file_id:
        return {"invoice_id": invoice.id, "status": "stale", "job_id": job_id}
    if job.status not in {"completed", "review"} or not job.result:
        raise HTTPException(409, "Extraction is not complete")
    existing_version = db.scalar(
        select(InvoiceVersion).where(
            InvoiceVersion.invoice_id == invoice_id,
            InvoiceVersion.extraction["job_id"].as_string() == job_id,
        )
    )
    if existing_version:
        if existing_version.version != invoice.current_version:
            return {"invoice_id": invoice.id, "status": "stale", "job_id": job_id}
        unresolved = (
            db.scalar(
                select(func.count(Finding.id)).where(
                    Finding.invoice_version_id == existing_version.id,
                    Finding.blocking.is_(True),
                    Finding.resolved.is_(False),
                )
            )
            or 0
        )
        return {
            "invoice_id": invoice_id,
            "status": invoice.status,
            "blocking_findings_count": unresolved,
            "route": _route_for(db, invoice, unresolved),
            "validation_version": existing_version.version,
        }
    if invoice.current_version and invoice.status not in {"received", "extracting", "validating"}:
        return {"invoice_id": invoice.id, "status": "stale", "job_id": job_id}
    extracted = dict(job.result.get("extraction", {}))
    vendor_id, ambiguous = resolve_vendor(
        str(extracted.get("vendor_name", "")), _vendor_candidates(db, invoice.workspace_id)
    )
    po_number = str(extracted.get("po_number", ""))
    po = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.workspace_id == invoice.workspace_id, PurchaseOrder.number == po_number
        )
    )
    receipts = (
        db.scalars(
            select(Receipt).where(
                Receipt.workspace_id == invoice.workspace_id, Receipt.po_id == po.id
            )
        ).all()
        if po
        else []
    )
    duplicate = bool(
        vendor_id
        and extracted.get("invoice_number")
        and db.scalar(
            select(Invoice.id)
            .where(
                Invoice.workspace_id == invoice.workspace_id,
                Invoice.vendor_id == vendor_id,
                Invoice.invoice_number == extracted["invoice_number"],
                Invoice.id != invoice.id,
                Invoice.status != "rejected",
            )
            .limit(1)
        )
    )
    policy = db.scalar(
        select(ApprovalPolicy).where(ApprovalPolicy.workspace_id == invoice.workspace_id)
    )
    findings = validate_document(
        extracted,
        {"currency": po.currency, "lines": po.lines} if po else None,
        [
            {"sku": line["sku"], "quantity": line.get("received_quantity", line.get("quantity", 0))}
            for r in receipts
            for line in r.lines
        ],
        duplicate,
        policy.tax_rate if policy else Decimal("0.075"),
    )
    if not vendor_id:
        from invoiceops.domain import RuleFinding

        findings.append(
            RuleFinding(
                "UNCERTAIN_VENDOR",
                "Vendor identity is ambiguous or unknown",
                {"vendor_name": extracted.get("vendor_name"), "ambiguous": ambiguous},
            )
        )
    if po and vendor_id and po.vendor_id != vendor_id:
        from invoiceops.domain import RuleFinding

        findings.append(
            RuleFinding(
                "PO_VENDOR_MISMATCH", "PO belongs to a different vendor", {"po_number": po_number}
            )
        )
    if job.status == "review":
        from invoiceops.domain import RuleFinding

        findings.append(
            RuleFinding(
                "EXTRACTION_REVIEW",
                "Document extraction requires review",
                {"warnings": job.result.get("warnings", [])},
            )
        )
    source = db.get(SourceFile, invoice.source_file_id)
    version_no = invoice.current_version + 1
    proposal_hash = canonical_hash(
        {
            "source_hash": source.content_hash,
            "version": version_no,
            "extraction": extracted,
            "findings": [f.code for f in findings],
        }
    )
    version = InvoiceVersion(
        workspace_id=invoice.workspace_id,
        invoice_id=invoice.id,
        version=version_no,
        proposal_hash=proposal_hash,
        extraction={**extracted, "job_id": job.id},
        evidence=extracted.get("evidence", []),
    )
    db.add(version)
    db.flush()
    for item in extracted.get("line_items", []):
        db.add(
            LineItem(
                workspace_id=invoice.workspace_id,
                invoice_version_id=version.id,
                sku=str(item.get("sku", "")),
                description=str(item.get("description", "")),
                quantity=Decimal(str(item.get("quantity", 0))),
                unit_price=money(item.get("unit_price", 0)),
                total=money(item.get("total", 0)),
            )
        )
    for finding in findings:
        db.add(
            Finding(
                workspace_id=invoice.workspace_id,
                invoice_id=invoice.id,
                invoice_version_id=version.id,
                code=finding.code,
                summary=finding.summary,
                blocking=finding.blocking,
                evidence=finding.evidence,
            )
        )
    invoice.vendor_id = vendor_id
    invoice.invoice_number = str(extracted.get("invoice_number", ""))
    invoice.po_number = po_number
    invoice.currency = str(extracted.get("currency", ""))
    invoice.amount = money(extracted.get("total", 0))
    invoice.current_version = version_no
    invoice.status = "validating"
    add_timeline(
        db, invoice, "validated", f"Version {version_no} produced {len(findings)} findings"
    )
    db.commit()
    return {
        "invoice_id": invoice.id,
        "status": "validating",
        "blocking_findings_count": len([f for f in findings if f.blocking]),
        "route": _route_for(db, invoice, len([f for f in findings if f.blocking])),
        "validation_version": version_no,
    }


def _route_for(db: Session, invoice: Invoice, blocking_count: int) -> str:
    if blocking_count:
        return "exception"
    policy = db.scalar(
        select(ApprovalPolicy).where(ApprovalPolicy.workspace_id == invoice.workspace_id)
    )
    threshold = (
        policy.high_amount_threshold if policy else money(get_settings().high_amount_threshold)
    )
    return "manager_and_reviewer" if money(invoice.amount or 0) >= threshold else "reviewer"


def routing_state(db: Session, invoice_id: str) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id)
    version = db.scalar(
        select(InvoiceVersion).where(
            InvoiceVersion.invoice_id == invoice.id,
            InvoiceVersion.version == invoice.current_version,
        )
    )
    if version is None:
        raise HTTPException(409, "No validation version")
    blocking = (
        db.scalar(
            select(func.count(Finding.id)).where(
                Finding.invoice_version_id == version.id,
                Finding.blocking.is_(True),
                Finding.resolved.is_(False),
            )
        )
        or 0
    )
    return {
        "invoice_id": invoice.id,
        "route": _route_for(db, invoice, blocking),
        "validation_version": invoice.current_version,
        "blocking_findings_count": blocking,
    }


def route_invoice(
    db: Session, invoice_id: str, route: str, validation_version: int
) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, lock=True)
    state = routing_state(db, invoice_id)
    if state["validation_version"] != validation_version or state["route"] != route:
        raise HTTPException(409, "Stale or incorrect route")
    if invoice.status != "validating":
        if invoice.status in {
            "needs_review",
            "awaiting_approval",
            "approved",
            "posting",
            "uncertain",
            "draft_created",
            "failed",
            "rejected",
        }:
            return {"invoice_id": invoice.id, "status": invoice.status, "route": route}
        raise HTTPException(409, "Invoice is not ready for routing")
    version = db.scalar(
        select(InvoiceVersion).where(
            InvoiceVersion.invoice_id == invoice_id, InvoiceVersion.version == validation_version
        )
    )
    if route == "exception":
        findings = db.scalars(
            select(Finding).where(
                Finding.invoice_version_id == version.id, Finding.resolved.is_(False)
            )
        ).all()
        for finding in findings:
            exists = db.scalar(
                select(BusinessException.id)
                .where(
                    BusinessException.invoice_id == invoice_id,
                    BusinessException.kind == finding.code,
                    BusinessException.status == "open",
                )
                .limit(1)
            )
            if not exists:
                db.add(
                    BusinessException(
                        workspace_id=invoice.workspace_id,
                        invoice_id=invoice.id,
                        kind=finding.code,
                        summary=finding.summary,
                        details=finding.evidence,
                    )
                )
        invoice.status = "needs_review"
        add_timeline(
            db,
            invoice,
            "exception",
            f"{len(findings)} unresolved finding(s) require operator review",
        )
    elif route in {"reviewer", "manager_and_reviewer"}:
        policy = db.scalar(
            select(ApprovalPolicy).where(ApprovalPolicy.workspace_id == invoice.workspace_id)
        )
        ttl = policy.ttl_hours if policy else get_settings().approval_ttl_hours
        roles = ("operator", "manager") if route == "manager_and_reviewer" else ("operator",)
        for role in roles:
            exists = db.scalar(
                select(Approval).where(
                    Approval.invoice_version_id == version.id, Approval.required_role == role
                )
            )
            if exists is None:
                db.add(
                    Approval(
                        workspace_id=invoice.workspace_id,
                        invoice_id=invoice.id,
                        invoice_version_id=version.id,
                        proposal_hash=version.proposal_hash,
                        required_role=role,
                        expires_at=now() + timedelta(hours=ttl),
                    )
                )
        invoice.status = "awaiting_approval"
        add_timeline(
            db,
            invoice,
            "awaiting_approval",
            f"Version {validation_version} sent for {', '.join(roles)} approval",
        )
    else:
        raise HTTPException(422, "Invalid route")
    db.commit()
    return {"invoice_id": invoice.id, "status": invoice.status, "route": route}


def expected_bill_payload(
    invoice: Invoice, version: InvoiceVersion, mapping: AccountingMapping
) -> dict[str, Any]:
    extracted = version.extraction
    return {
        "Type": "ACCPAY",
        "Status": "DRAFT",
        "Contact": {"ContactID": mapping.accounting_contact_id},
        "InvoiceNumber": invoice.invoice_number,
        "Date": extracted.get("invoice_date"),
        "DueDate": extracted.get("due_date"),
        "CurrencyCode": invoice.currency,
        "LineItems": [
            {
                "Description": x.get("description"),
                "Quantity": x.get("quantity"),
                "UnitAmount": x.get("unit_price"),
                "AccountCode": mapping.expense_account,
            }
            for x in extracted.get("line_items", [])
        ],
    }


def claim_posting(db: Session, invoice_id: str) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, lock=True)
    version = db.scalar(
        select(InvoiceVersion).where(
            InvoiceVersion.invoice_id == invoice.id,
            InvoiceVersion.version == invoice.current_version,
        )
    )
    if version is None:
        raise HTTPException(409, "No extraction version")
    approvals = db.scalars(select(Approval).where(Approval.invoice_version_id == version.id)).all()
    policy = db.scalar(
        select(ApprovalPolicy).where(ApprovalPolicy.workspace_id == invoice.workspace_id)
    )
    threshold = (
        policy.high_amount_threshold if policy else money(get_settings().high_amount_threshold)
    )
    roles = required_approval_roles(money(invoice.amount or 0), threshold)
    valid_approvals = [
        a
        for a in approvals
        if a.status == "approved"
        and a.proposal_hash == version.proposal_hash
        and as_utc(a.expires_at) >= now()
    ]
    approved_roles = {a.required_role for a in valid_approvals}
    blocking = (
        db.scalar(
            select(func.count(Finding.id)).where(
                Finding.invoice_version_id == version.id,
                Finding.blocking.is_(True),
                Finding.resolved.is_(False),
            )
        )
        or 0
    )
    duplicate = bool(
        invoice.vendor_id
        and invoice.invoice_number
        and (
            db.scalar(
                select(SimulatedBill.id)
                .where(
                    SimulatedBill.workspace_id == invoice.workspace_id,
                    SimulatedBill.vendor_id == invoice.vendor_id,
                    SimulatedBill.invoice_number == invoice.invoice_number,
                )
                .limit(1)
            )
            or db.scalar(
                select(Invoice.id)
                .where(
                    Invoice.workspace_id == invoice.workspace_id,
                    Invoice.vendor_id == invoice.vendor_id,
                    Invoice.invoice_number == invoice.invoice_number,
                    Invoice.id != invoice.id,
                    Invoice.status != "rejected",
                )
                .limit(1)
            )
        )
    )
    existing = db.scalar(select(PostingOperation).where(PostingOperation.invoice_id == invoice_id))
    distinct_approvers = len({a.decided_by for a in valid_approvals}) == len(valid_approvals)
    retry_requested = existing is not None and existing.status == "retry_requested"
    if (
        invoice.status != "approved"
        or (retry_requested and existing.invoice_version_id != version.id)
        or not may_post(
            current_version=invoice.current_version,
            approval_version=version.version,
            required_roles=roles,
            approved_roles=approved_roles,
            blocking_findings=blocking,
            duplicate_identity=duplicate,
            posted=existing is not None and not retry_requested,
        )
        or not distinct_approvers
    ):
        if retry_requested:
            existing.status = "reconciled_absent"
            invoice.status = "failed"
            add_timeline(db, invoice, "retry_blocked", "Posting retry failed current policy checks")
            db.commit()
        return {
            "claimed": False,
            "reason": "blocked, stale, duplicate, or already claimed",
            "invoice_id": invoice_id,
        }
    mapping = db.scalar(
        select(AccountingMapping).where(
            AccountingMapping.workspace_id == invoice.workspace_id,
            AccountingMapping.vendor_id == invoice.vendor_id,
        )
    )
    if mapping is None:
        if retry_requested:
            existing.status = "reconciled_absent"
            invoice.status = "failed"
            db.commit()
        raise HTTPException(409, "Vendor accounting mapping is missing")
    bill_payload = expected_bill_payload(invoice, version, mapping)
    if retry_requested:
        operation = existing
        operation.status = "claimed"
        operation.attempts += 1
        operation.last_error = None
    else:
        operation = PostingOperation(
            workspace_id=invoice.workspace_id,
            invoice_id=invoice.id,
            invoice_version_id=version.id,
            operation_key=f"invoiceops:{invoice.workspace_id}:{invoice.id}",
            status="claimed",
            attempts=1,
        )
        db.add(operation)
    invoice.status = "posting"
    add_timeline(db, invoice, "posting", "Accounting draft operation claimed")
    db.commit()
    return {
        "claimed": True,
        "invoice_id": invoice.id,
        "operation_id": operation.id,
        "attempt": operation.attempts,
        "operation_key": operation.operation_key,
        "workspace_id": invoice.workspace_id,
        "vendor_id": invoice.vendor_id,
        "invoice_number": invoice.invoice_number,
        "amount": str(invoice.amount),
        "currency": invoice.currency,
        "bill_payload": bill_payload,
    }


def record_post_result(
    db: Session,
    operation_id: str,
    attempt: int,
    result_status: str,
    accounting_id: str | None,
    error: str | None,
) -> dict[str, Any]:
    operation = db.get(PostingOperation, operation_id)
    if operation is None:
        raise HTTPException(404, "Operation not found")
    invoice = get_invoice(db, operation.invoice_id, lock=True)
    operation = db.scalar(
        select(PostingOperation)
        .where(PostingOperation.id == operation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if operation.attempts != attempt:
        raise HTTPException(409, "Stale posting attempt")
    if operation.status == "accepted":
        return {"status": "draft_created", "accounting_id": operation.accounting_id}
    if operation.status not in {"claimed", "uncertain"}:
        raise HTTPException(409, "Posting operation is not awaiting a result")
    if result_status == "accepted" and accounting_id:
        operation.status = "accepted"
        operation.accounting_id = accounting_id
        invoice.accounting_id = accounting_id
        invoice.status = "draft_created"
        add_timeline(db, invoice, "draft_created", f"Draft accounting record {accounting_id} saved")
    elif result_status == "uncertain":
        operation.status = "uncertain"
        operation.last_error = (error or "Provider outcome unknown")[:500]
        invoice.status = "uncertain"
        add_timeline(
            db, invoice, "uncertain", "Accounting write outcome unknown; reconciliation required"
        )
    else:
        operation.status = "failed"
        operation.last_error = (error or "Provider declined write")[:500]
        invoice.status = "failed"
        db.add(
            BusinessException(
                workspace_id=invoice.workspace_id,
                invoice_id=invoice.id,
                kind="ACCOUNTING_FAILURE",
                summary=operation.last_error,
            )
        )
        add_timeline(db, invoice, "failed", operation.last_error)
    db.commit()
    return {"status": invoice.status, "accounting_id": invoice.accounting_id}


def reconcile_result(
    db: Session, operation_id: str, found: bool, accounting_id: str | None
) -> dict[str, Any]:
    operation = db.get(PostingOperation, operation_id)
    if operation is None:
        raise HTTPException(409, "No uncertain operation")
    invoice = get_invoice(db, operation.invoice_id, lock=True)
    operation = db.scalar(
        select(PostingOperation)
        .where(PostingOperation.id == operation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if operation.status != "uncertain":
        raise HTTPException(409, "No uncertain operation")
    if found and not accounting_id:
        raise HTTPException(422, "Found draft requires an accounting ID")
    if found:
        return record_post_result(
            db, operation_id, operation.attempts, "accepted", accounting_id, None
        )
    operation.status = "reconciled_absent"
    operation.last_error = "No provider bill found; operator review required before retry"
    invoice.status = "failed"
    db.add(
        BusinessException(
            workspace_id=invoice.workspace_id,
            invoice_id=invoice.id,
            kind="RECONCILE_NOT_FOUND",
            summary=operation.last_error,
        )
    )
    db.commit()
    return {"status": "failed", "reason": operation.last_error}


def request_post_retry(
    db: Session, invoice_id: str, workspace_id: str, actor_id: str, note: str
) -> dict[str, Any]:
    if get_settings().accounting_provider != "demo":
        raise HTTPException(409, "Connected provider retry requires a verified provider lookup")
    invoice = get_invoice(db, invoice_id, workspace_id, lock=True)
    operation = db.scalar(
        select(PostingOperation).where(PostingOperation.invoice_id == invoice.id).with_for_update()
    )
    if operation is None or operation.status != "reconciled_absent" or invoice.status != "failed":
        raise HTTPException(409, "Retry requires a completed lookup confirming no draft")
    version = db.get(InvoiceVersion, operation.invoice_version_id)
    if version is None or version.version != invoice.current_version:
        raise HTTPException(409, "Approved invoice version changed")
    operation.status = "retry_requested"
    invoice.status = "approved"
    add_timeline(db, invoice, "retry_requested", f"Operator {actor_id} requested retry: {note}")
    db.commit()
    return {
        "invoice_id": invoice.id,
        "status": "retry_requested",
        "attempt": operation.attempts + 1,
    }


def list_uncertain_operations(db: Session) -> list[dict[str, str]]:
    # The provider request has a 30 second timeout. Give an orphaned claim four
    # minutes before treating its outcome as unknown; lookup precedes any retry.
    cutoff = now() - timedelta(minutes=4)
    stale_ids = db.scalars(
        select(PostingOperation.id)
        .where(PostingOperation.status == "claimed", PostingOperation.updated_at < cutoff)
        .order_by(PostingOperation.updated_at)
        .limit(100)
    ).all()
    for operation_id in stale_ids:
        operation = db.get(PostingOperation, operation_id)
        invoice = get_invoice(db, operation.invoice_id, lock=True)
        operation = db.scalar(
            select(PostingOperation)
            .where(PostingOperation.id == operation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if operation.status != "claimed" or as_utc(operation.updated_at) >= cutoff:
            continue
        operation.status = "uncertain"
        operation.last_error = "Claim outlived its workflow; provider outcome requires lookup"
        if invoice.status == "posting":
            invoice.status = "uncertain"
        add_timeline(db, invoice, "uncertain", operation.last_error)
    db.commit()
    operations = db.scalars(
        select(PostingOperation)
        .where(PostingOperation.status == "uncertain")
        .order_by(PostingOperation.updated_at)
        .limit(100)
    ).all()
    return [
        {"operation_id": op.id, "operation_key": op.operation_key, "invoice_id": op.invoice_id}
        for op in operations
    ]


def check_xero_draft(
    db: Session, operation_id: str, attempt: int, draft: dict[str, Any]
) -> dict[str, Any]:
    operation = db.get(PostingOperation, operation_id)
    if operation is None or operation.attempts != attempt:
        raise HTTPException(409, "Unknown or stale posting attempt")
    if operation.status not in {"claimed", "uncertain"}:
        raise HTTPException(409, "Posting operation is not awaiting verification")
    invoice = get_invoice(db, operation.invoice_id)
    version = db.get(InvoiceVersion, operation.invoice_version_id)
    mapping = db.scalar(
        select(AccountingMapping).where(
            AccountingMapping.workspace_id == invoice.workspace_id,
            AccountingMapping.vendor_id == invoice.vendor_id,
        )
    )
    if version is None or mapping is None or version.version != invoice.current_version:
        raise HTTPException(409, "Approved invoice version or accounting mapping changed")
    expected_tax = money(version.extraction.get("tax", 0))
    expected_subtotal = money(version.extraction.get("subtotal", invoice.amount - expected_tax))
    try:
        amount_matches = (
            abs(money(draft.get("Total")) - money(invoice.amount)) <= Decimal("0.01")
            and abs(money(draft.get("TotalTax")) - expected_tax) <= Decimal("0.01")
            and abs(money(draft.get("SubTotal")) - expected_subtotal) <= Decimal("0.01")
        )
    except ValueError:
        amount_matches = False
    identity_matches = (
        draft.get("Type") == "ACCPAY"
        and draft.get("Status") == "DRAFT"
        and draft.get("InvoiceNumber") == invoice.invoice_number
        and draft.get("CurrencyCode") == invoice.currency
        and isinstance(draft.get("Contact"), dict)
        and draft["Contact"].get("ContactID") == mapping.accounting_contact_id
        and isinstance(draft.get("InvoiceID"), str)
        and bool(draft["InvoiceID"])
    )
    verified = identity_matches and amount_matches
    return {
        "match": verified,
        "accounting_id": draft.get("InvoiceID") if verified else None,
        "reason": None if verified else "xero_draft_identity_or_amount_mismatch",
    }


def xero_reconcile_context(db: Session, operation_id: str) -> dict[str, Any]:
    operation = db.get(PostingOperation, operation_id)
    if operation is None or operation.status != "uncertain":
        raise HTTPException(409, "No uncertain operation")
    invoice = get_invoice(db, operation.invoice_id)
    mapping = db.scalar(
        select(AccountingMapping).where(
            AccountingMapping.workspace_id == invoice.workspace_id,
            AccountingMapping.vendor_id == invoice.vendor_id,
        )
    )
    if mapping is None:
        raise HTTPException(409, "Vendor accounting mapping is missing")
    return {
        "operation_id": operation.id,
        "attempt": operation.attempts,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "contact_id": mapping.accounting_contact_id,
    }


def create_digest(db: Session) -> list[dict[str, Any]]:
    output = []
    for workspace in db.scalars(select(Workspace)).all():
        rows = db.execute(
            select(Invoice.status, func.count(Invoice.id))
            .where(Invoice.workspace_id == workspace.id)
            .group_by(Invoice.status)
        ).all()
        counts = {status: count for status, count in rows}
        run = DigestRun(workspace_id=workspace.id, counts=counts)
        db.add(run)
        output.append({"workspace_id": workspace.id, "counts": counts})
    db.commit()
    return output
