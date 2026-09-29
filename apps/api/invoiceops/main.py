"""Authenticated portal API, n8n callbacks, extraction jobs, and local connectors."""

import base64
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
import pymupdf
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from invoiceops.business import (
    add_timeline,
    check_xero_draft,
    claim_posting,
    create_digest,
    expected_bill_payload,
    get_invoice,
    list_uncertain_operations,
    receive_event,
    reconcile_result,
    record_post_result,
    request_post_retry,
    route_invoice,
    routing_state,
    submit_job,
    validate_invoice,
    xero_reconcile_context,
)
from invoiceops.config import get_settings
from invoiceops.db import get_db
from invoiceops.models import (
    AccountingMapping,
    Approval,
    ArchiveRecord,
    BusinessException,
    DigestRun,
    DocumentJob,
    Finding,
    Invoice,
    InvoiceVersion,
    PostingOperation,
    PurchaseOrder,
    Receipt,
    SimulatedBill,
    SourceFile,
    TimelineEvent,
    User,
    UserSession,
    Vendor,
    Workspace,
    as_utc,
    now,
)
from invoiceops.security import (
    create_session,
    current_user,
    internal_auth,
    operator,
    require_same_workspace,
    token_digest,
    verify_password,
)
from invoiceops.worker import expire_old_jobs, start_worker, stop_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().enable_worker:
        start_worker()
    yield
    if get_settings().enable_worker:
        stop_worker()


app = FastAPI(title="InvoiceOps", version="0.1.0", lifespan=lifespan)
internal = APIRouter(prefix="/internal", dependencies=[Depends(internal_auth)])
simulator = APIRouter(prefix="/sim", dependencies=[Depends(internal_auth)])
portal = APIRouter(prefix="/api")


class LoginInput(BaseModel):
    username: str
    password: str


class JobInput(BaseModel):
    invoice_id: str


class ValidateInput(BaseModel):
    job_id: str


class RouteInput(BaseModel):
    route: Literal["exception", "reviewer", "manager_and_reviewer"]
    validation_version: int


class ClaimInput(BaseModel):
    invoice_id: str


class PostResultInput(BaseModel):
    operation_id: str
    attempt: int = Field(ge=1)
    status: Literal["accepted", "uncertain", "declined", "credential_error"]
    accounting_id: str | None = None
    error: str | None = None


class ReconcileInput(BaseModel):
    operation_id: str
    found: bool
    accounting_id: str | None = None


class XeroDraftCheckInput(BaseModel):
    operation_id: str
    attempt: int = Field(ge=1)
    invoice: dict[str, Any]


class DecisionInput(BaseModel):
    decision: Literal["approve", "reject"]
    proposal_version: int
    note: str = Field(default="", max_length=1000)


class ResolveInput(BaseModel):
    resolution: Literal["accept", "reject", "request_revision"]
    note: str = Field(min_length=8, max_length=1000)


class RetryPostingInput(BaseModel):
    note: str = Field(min_length=8, max_length=1000)


class FailedInput(BaseModel):
    job_id: str
    reason: str = Field(max_length=500)


class WorkflowErrorInput(BaseModel):
    invoice_id: str | None = None
    workflow_id: str
    execution_id: str
    message: str = Field(max_length=500)
    stage: str


class SimulatorBillInput(BaseModel):
    operation_key: str
    workspace_id: str
    vendor_id: str
    invoice_number: str
    amount: Decimal
    currency: str
    bill_payload: dict[str, Any]


class SimulatorOutcomeInput(BaseModel):
    outcome: Literal["accepted", "timeout", "declined", "credential_error"]


def _date(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def notify_n8n(url: str, invoice_id: str, version: int | None = None) -> None:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                url,
                json={"invoice_id": invoice_id, "validation_version": version},
                headers={"X-Internal-Token": settings.internal_token},
            )
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        log.exception("n8n_notification_failed", extra={"invoice_id": invoice_id})


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "mode": get_settings().mode}


@internal.post("/intake")
def intake(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    return receive_event(db, payload)


@internal.post("/jobs")
def create_job(body: JobInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return submit_job(db, body.invoice_id)


@internal.get("/jobs/pending-completions")
def pending_completions(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    expire_old_jobs()
    jobs = db.scalars(
        select(DocumentJob)
        .where(
            DocumentJob.status.in_(["completed", "review", "failed"]),
            DocumentJob.completion_notified.is_(False),
        )
        .order_by(DocumentJob.created_at)
        .limit(100)
    ).all()
    return [{"job_id": job.id, "invoice_id": job.invoice_id} for job in jobs]


@internal.get("/jobs/{job_id}")
def job_status(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    expire_old_jobs()
    job = db.get(DocumentJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    data = {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "failure_reason": job.failure_reason,
    }
    if job.result:
        data.update(job.result)
    return data


@internal.post("/jobs/{job_id}/ack")
def acknowledge_completion(job_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    job = db.get(DocumentJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status not in {"completed", "review", "failed"}:
        raise HTTPException(409, "Job is not complete")
    job.completion_notified = True
    db.commit()
    return {"status": "acknowledged"}


@internal.post("/invoices/{invoice_id}/validate")
def validate(invoice_id: str, body: ValidateInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return validate_invoice(db, invoice_id, body.job_id)


@internal.get("/invoices/{invoice_id}/routing-state")
def current_route(invoice_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return routing_state(db, invoice_id)


@internal.post("/invoices/{invoice_id}/route")
def route(invoice_id: str, body: RouteInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return route_invoice(db, invoice_id, body.route, body.validation_version)


@internal.post("/invoices/{invoice_id}/processing-failed")
def processing_failed(
    invoice_id: str, body: FailedInput, db: Session = Depends(get_db)
) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, lock=True)
    job = db.get(DocumentJob, body.job_id)
    if job is None or job.invoice_id != invoice_id:
        raise HTTPException(404, "Job not found")
    existing = db.scalar(
        select(BusinessException).where(
            BusinessException.invoice_id == invoice.id,
            BusinessException.kind == "EXTRACTION_FAILURE",
            BusinessException.details["job_id"].as_string() == body.job_id,
        )
    )
    if job.source_file_id != invoice.source_file_id or (
        invoice.status not in {"received", "extracting"} and existing is None
    ):
        return {"status": "stale"}
    if existing is None:
        invoice.status = "failed"
        db.add(
            BusinessException(
                workspace_id=invoice.workspace_id,
                invoice_id=invoice.id,
                kind="EXTRACTION_FAILURE",
                summary=body.reason,
                details={"job_id": body.job_id},
            )
        )
        add_timeline(db, invoice, "failed", body.reason)
    db.commit()
    return {"status": "failed"}


@internal.post("/post/claim")
def post_claim(body: ClaimInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return claim_posting(db, body.invoice_id)


@internal.post("/post/result")
def post_result(body: PostResultInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return record_post_result(
        db, body.operation_id, body.attempt, body.status, body.accounting_id, body.error
    )


@internal.get("/reconcile/uncertain")
def uncertain_operations(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    return list_uncertain_operations(db)


@internal.post("/reconcile/result")
def reconcile(body: ReconcileInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return reconcile_result(db, body.operation_id, body.found, body.accounting_id)


@internal.post("/xero/draft-check")
def xero_draft_check(body: XeroDraftCheckInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    return check_xero_draft(db, body.operation_id, body.attempt, body.invoice)


@internal.get("/reconcile/xero-context/{operation_id}")
def xero_context(operation_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return xero_reconcile_context(db, operation_id)


@internal.get("/recovery/pending-postings")
def pending_postings(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    invoices = db.scalars(
        select(Invoice).where(Invoice.status == "approved").order_by(Invoice.updated_at).limit(100)
    ).all()
    return [
        {"invoice_id": invoice.id}
        for invoice in invoices
        if (
            (
                operation := db.scalar(
                    select(PostingOperation).where(PostingOperation.invoice_id == invoice.id)
                )
            )
            is None
            or operation.status == "retry_requested"
        )
    ]


@internal.get("/recovery/pending-routes")
def pending_routes(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.status == "validating")
        .order_by(Invoice.updated_at)
        .limit(100)
    ).all()
    return [routing_state(db, invoice.id) for invoice in invoices]


@internal.get("/recovery/pending-archives")
def pending_archives(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    invoices = db.scalars(
        select(Invoice)
        .where(
            Invoice.status == "draft_created",
            Invoice.accounting_id.is_not(None),
            ~select(ArchiveRecord.id).where(ArchiveRecord.invoice_id == Invoice.id).exists(),
        )
        .order_by(Invoice.updated_at)
        .limit(100)
    ).all()
    return [{"invoice_id": invoice.id} for invoice in invoices]


@internal.post("/invoices/{invoice_id}/archive")
def archive(invoice_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, lock=True)
    if invoice.status != "draft_created" or not invoice.accounting_id:
        raise HTTPException(409, "Only completed draft invoices can be archived")
    existing = db.scalar(select(ArchiveRecord).where(ArchiveRecord.invoice_id == invoice_id))
    if existing:
        return {"status": "archived", "export_path": existing.export_path}
    version = db.scalar(
        select(InvoiceVersion).where(
            InvoiceVersion.invoice_id == invoice.id,
            InvoiceVersion.version == invoice.current_version,
        )
    )
    source = db.get(SourceFile, invoice.source_file_id)
    path = (
        get_settings().data_dir
        / "archive"
        / invoice.workspace_id
        / f"{invoice.id}-v{version.version}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    export = {
        "schema_version": "invoiceops.archive.v1",
        "invoice_id": invoice.id,
        "workspace_id": invoice.workspace_id,
        "version": version.version,
        "proposal_hash": version.proposal_hash,
        "source_hash": source.content_hash,
        "accounting_id": invoice.accounting_id,
        "extraction": version.extraction,
        "evidence": version.evidence,
    }
    path.write_text(__import__("json").dumps(export, indent=2, default=str), encoding="utf-8")
    db.add(
        ArchiveRecord(
            workspace_id=invoice.workspace_id,
            invoice_id=invoice.id,
            invoice_version_id=version.id,
            source_file_id=source.id,
            accounting_id=invoice.accounting_id,
            export_path=str(path),
        )
    )
    add_timeline(db, invoice, "archived", "Source, version evidence, and draft reference archived")
    db.commit()
    return {"status": "archived", "export_path": str(path)}


@internal.post("/digests/run")
def run_digests(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return create_digest(db)


@internal.post("/workflow-errors")
def workflow_error(body: WorkflowErrorInput, db: Session = Depends(get_db)) -> dict[str, str]:
    if body.invoice_id:
        invoice = get_invoice(db, body.invoice_id)
        db.add(
            BusinessException(
                workspace_id=invoice.workspace_id,
                invoice_id=invoice.id,
                kind="WORKFLOW_ERROR",
                summary=body.message,
                details={
                    "workflow_id": body.workflow_id,
                    "execution_id": body.execution_id,
                    "stage": body.stage,
                },
            )
        )
        add_timeline(db, invoice, "workflow_error", body.message)
        db.commit()
    else:
        log.error(
            "workflow_error workflow=%s execution=%s stage=%s message=%s",
            body.workflow_id,
            body.execution_id,
            body.stage,
            body.message,
        )
    return {"status": "recorded"}


@internal.post("/simulator/invoices/{invoice_id}/outcome")
def set_simulator_outcome(
    invoice_id: str, body: SimulatorOutcomeInput, db: Session = Depends(get_db)
) -> dict[str, str]:
    if get_settings().mode != "DEMO":
        raise HTTPException(403, "Simulator controls are demo only")
    invoice = get_invoice(db, invoice_id)
    invoice.simulator_outcome = body.outcome
    db.commit()
    return {"outcome": body.outcome}


@simulator.post("/accounting/bills")
def create_simulated_bill(body: SimulatorBillInput, db: Session = Depends(get_db)) -> Response:
    if get_settings().mode != "DEMO":
        raise HTTPException(403, "Accounting simulator is demo only")
    operation = db.scalar(
        select(PostingOperation).where(PostingOperation.operation_key == body.operation_key)
    )
    if (
        operation is None
        or operation.workspace_id != body.workspace_id
        or operation.status not in {"claimed", "uncertain", "accepted"}
    ):
        raise HTTPException(409, "No matching claimed operation")
    invoice = get_invoice(db, operation.invoice_id)
    version = db.get(InvoiceVersion, operation.invoice_version_id)
    mapping = db.scalar(
        select(AccountingMapping).where(
            AccountingMapping.workspace_id == invoice.workspace_id,
            AccountingMapping.vendor_id == invoice.vendor_id,
        )
    )
    if (
        invoice.vendor_id != body.vendor_id
        or invoice.invoice_number != body.invoice_number
        or invoice.amount != body.amount
        or invoice.currency != body.currency
        or version is None
        or version.version != invoice.current_version
        or mapping is None
        or body.bill_payload != expected_bill_payload(invoice, version, mapping)
    ):
        raise HTTPException(409, "Bill differs from approved invoice version")
    previous = db.scalar(
        select(SimulatedBill).where(SimulatedBill.operation_key == body.operation_key)
    )
    if previous:
        return JSONResponse({"status": "accepted", "accounting_id": previous.id, "replayed": True})
    if invoice.simulator_outcome == "credential_error":
        return JSONResponse(
            {
                "status": "credential_error",
                "error": "Simulator credential rejected; verify connector configuration",
            },
            status_code=401,
        )
    if invoice.simulator_outcome == "declined":
        return JSONResponse(
            {"status": "declined", "error": "Simulator declined draft"}, status_code=422
        )
    existing_identity = db.scalar(
        select(SimulatedBill).where(
            SimulatedBill.workspace_id == body.workspace_id,
            SimulatedBill.vendor_id == body.vendor_id,
            SimulatedBill.invoice_number == body.invoice_number,
        )
    )
    if existing_identity:
        return JSONResponse(
            {"status": "declined", "error": "Duplicate vendor/invoice identity"}, status_code=409
        )
    bill = SimulatedBill(
        id=f"SIM-{uuid4().hex[:12].upper()}",
        workspace_id=body.workspace_id,
        vendor_id=body.vendor_id,
        invoice_number=body.invoice_number,
        operation_key=body.operation_key,
        amount=body.amount,
        currency=body.currency,
        status="DRAFT",
    )
    db.add(bill)
    db.commit()
    if invoice.simulator_outcome == "timeout":
        return JSONResponse(
            {"status": "timeout", "error": "Simulated response lost after durable write"},
            status_code=504,
        )
    return JSONResponse({"status": "accepted", "accounting_id": bill.id}, status_code=201)


@simulator.get("/accounting/bills/by-operation/{operation_key:path}")
def bill_by_operation(operation_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    bill = db.scalar(select(SimulatedBill).where(SimulatedBill.operation_key == operation_key))
    return {"found": bill is not None, "accounting_id": bill.id if bill else None}


app.include_router(internal)
app.include_router(simulator)


@portal.post("/login")
def login(body: LoginInput, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == body.username.lower().strip()))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_session(db, user)
    response.set_cookie(
        "session_token",
        token,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="strict",
        max_age=12 * 3600,
        path="/",
    )
    workspace = db.get(Workspace, user.workspace_id)
    return {
        "user": {"id": user.id, "name": user.name, "role": user.role},
        "workspace": {"id": workspace.id, "name": workspace.name},
        "mode": workspace.mode,
    }


@portal.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    cookie = request.cookies.get("session_token")
    if cookie:
        session = db.get(UserSession, token_digest(cookie))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie("session_token", path="/")
    return {"status": "signed_out"}


@portal.get("/session")
def session(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    workspace = db.get(Workspace, user.workspace_id)
    return {
        "user": {"id": user.id, "name": user.name, "role": user.role},
        "workspace": {"id": workspace.id, "name": workspace.name},
        "mode": workspace.mode,
    }


def _invoice_summary(db: Session, invoice: Invoice) -> dict[str, Any]:
    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    findings_count = (
        db.scalar(
            select(func.count(Finding.id)).where(
                Finding.invoice_id == invoice.id, Finding.resolved.is_(False)
            )
        )
        or 0
    )
    approvals = db.scalars(select(Approval).where(Approval.invoice_id == invoice.id)).all()
    days = max(0, (now().date() - invoice.created_at.date()).days)
    return {
        "id": invoice.id,
        "vendor_name": vendor.name if vendor else "Unresolved vendor",
        "invoice_number": invoice.invoice_number or "Pending extraction",
        "amount": str(invoice.amount or "0.00"),
        "currency": invoice.currency or "—",
        "status": invoice.status,
        "age_days": days,
        "received_at": _date(invoice.created_at),
        "po_number": invoice.po_number,
        "findings_count": findings_count,
        "approval_progress": {
            "approved": len([a for a in approvals if a.status == "approved"]),
            "required": len(approvals),
        },
        "vendor_id": invoice.vendor_id,
        "current_version": invoice.current_version,
    }


@portal.get("/invoices")
def invoices(
    status: str | None = None,
    q: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = select(Invoice).where(Invoice.workspace_id == user.workspace_id)
    if status:
        statement = statement.where(Invoice.status == status)
    if q:
        term = f"%{q.strip()[:100]}%"
        statement = statement.outerjoin(Vendor, Invoice.vendor_id == Vendor.id).where(
            (Invoice.invoice_number.ilike(term))
            | (Vendor.name.ilike(term))
            | (Invoice.po_number.ilike(term))
        )
    rows = db.scalars(statement.order_by(Invoice.created_at.desc()).limit(500)).all()
    return {"items": [_invoice_summary(db, invoice) for invoice in rows], "total": len(rows)}


def _signed_source_url(source: SourceFile, workspace_id: str) -> str:
    expires = int((now() + timedelta(minutes=10)).timestamp())
    data = f"{source.id}:{workspace_id}:{expires}".encode()
    signature = hmac.new(get_settings().session_secret.encode(), data, hashlib.sha256).hexdigest()
    return f"/api/files/{source.id}?exp={expires}&sig={signature}"


@portal.get("/invoices/{invoice_id}")
def invoice_detail(
    invoice_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    invoice = get_invoice(db, invoice_id, user.workspace_id)
    versions = db.scalars(
        select(InvoiceVersion)
        .where(InvoiceVersion.invoice_id == invoice_id)
        .order_by(InvoiceVersion.version.desc())
    ).all()
    current = versions[0] if versions else None
    findings = db.scalars(select(Finding).where(Finding.invoice_id == invoice_id)).all()
    approvals = db.scalars(select(Approval).where(Approval.invoice_id == invoice_id)).all()
    timeline = db.scalars(
        select(TimelineEvent)
        .where(TimelineEvent.invoice_id == invoice_id)
        .order_by(TimelineEvent.created_at)
    ).all()
    po = (
        db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.workspace_id == user.workspace_id,
                PurchaseOrder.number == invoice.po_number,
            )
        )
        if invoice.po_number
        else None
    )
    receipts = (
        db.scalars(
            select(Receipt).where(Receipt.po_id == po.id, Receipt.workspace_id == user.workspace_id)
        ).all()
        if po
        else []
    )
    source = db.get(SourceFile, invoice.source_file_id)
    data = _invoice_summary(db, invoice)
    data.update(
        {
            "vendor_id": invoice.vendor_id,
            "source_url": _signed_source_url(source, user.workspace_id),
            "versions": [
                {
                    "version": v.version,
                    "created_at": _date(v.created_at),
                    "proposal_hash": v.proposal_hash,
                    "extraction": v.extraction,
                    "evidence": v.evidence,
                }
                for v in versions
            ],
            "line_items": current.extraction.get("line_items", []) if current else [],
            "findings": [
                {
                    "id": f.id,
                    "code": f.code,
                    "summary": f.summary,
                    "blocking": f.blocking,
                    "resolved": f.resolved,
                    "evidence": f.evidence,
                }
                for f in findings
            ],
            "approvals": [
                {
                    "id": a.id,
                    "required_role": a.required_role,
                    "status": a.status,
                    "proposal_version": next(
                        (v.version for v in versions if v.id == a.invoice_version_id), 0
                    ),
                    "expires_at": _date(a.expires_at),
                    "decided_at": _date(a.decided_at),
                }
                for a in approvals
            ],
            "purchase_order": {
                "id": po.id,
                "number": po.number,
                "currency": po.currency,
                "lines": po.lines,
            }
            if po
            else None,
            "receipts": [
                {"id": r.id, "lines": r.lines, "received_at": _date(r.received_at)}
                for r in receipts
            ],
            "timeline": [
                {
                    "id": event.id,
                    "event": event.event,
                    "detail": event.detail,
                    "created_at": _date(event.created_at),
                }
                for event in timeline
            ],
            "accounting_id": invoice.accounting_id,
        }
    )
    return data


@portal.get("/files/{source_id}")
def source_file(
    source_id: str,
    exp: int,
    sig: str,
    preview_page: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    source = db.get(SourceFile, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    require_same_workspace(source.workspace_id, user)
    if exp < int(now().timestamp()) or exp > int((now() + timedelta(minutes=11)).timestamp()):
        raise HTTPException(403, "Source link expired")
    expected = hmac.new(
        get_settings().session_secret.encode(),
        f"{source.id}:{user.workspace_id}:{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(403, "Invalid source link")
    path = Path(source.path).resolve()
    if not path.is_relative_to(get_settings().data_dir.resolve()) or not path.is_file():
        raise HTTPException(404, "Source file unavailable")
    if preview_page is not None:
        if preview_page < 1 or preview_page > 100:
            raise HTTPException(400, "Invalid preview page")
        if source.mime_type == "application/pdf":
            try:
                with pymupdf.open(path) as document:
                    if preview_page > document.page_count:
                        raise HTTPException(404, "Preview page not found")
                    page = document.load_page(preview_page - 1)
                    scale = min(1.5, 1000 / max(page.rect.width, 1))
                    image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    return Response(
                        content=image.tobytes("png"),
                        media_type="image/png",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
                    )
            except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
                raise HTTPException(422, "Source PDF cannot be previewed") from exc
        if source.mime_type not in {"image/png", "image/jpeg"} or preview_page != 1:
            raise HTTPException(415, "Source preview is unavailable")
    return FileResponse(
        path,
        media_type=source.mime_type,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )


@portal.get("/approvals")
def approvals(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(
        select(Approval)
        .where(Approval.workspace_id == user.workspace_id)
        .order_by(Approval.expires_at)
    ).all()
    items = []
    for approval in rows:
        invoice = db.get(Invoice, approval.invoice_id)
        vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
        version = db.get(InvoiceVersion, approval.invoice_version_id)
        items.append(
            {
                "id": approval.id,
                "invoice_id": invoice.id,
                "vendor_name": vendor.name if vendor else "Unresolved vendor",
                "invoice_number": invoice.invoice_number,
                "amount": str(invoice.amount or "0.00"),
                "currency": invoice.currency,
                "role": approval.required_role,
                "status": approval.status,
                "proposal_version": version.version,
                "expires_at": _date(approval.expires_at),
            }
        )
    return {"items": items}


@portal.post("/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: DecisionInput,
    background: BackgroundTasks,
    user: User = Depends(operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    approval = db.scalar(
        select(Approval)
        .where(Approval.id == approval_id, Approval.workspace_id == user.workspace_id)
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(404, "Approval not found")
    invoice = get_invoice(db, approval.invoice_id, user.workspace_id, lock=True)
    version = db.get(InvoiceVersion, approval.invoice_version_id)
    if approval.status != "pending" or as_utc(approval.expires_at) < now():
        raise HTTPException(409, "Decision was already used or expired")
    if user.role != approval.required_role:
        raise HTTPException(403, f"{approval.required_role} role required")
    if (
        invoice.current_version != body.proposal_version
        or version.version != body.proposal_version
        or approval.proposal_hash != version.proposal_hash
    ):
        raise HTTPException(409, "Extraction or validation version changed")
    prior = db.scalar(
        select(Approval).where(
            Approval.invoice_version_id == version.id,
            Approval.decided_by == user.id,
            Approval.status == "approved",
        )
    )
    if prior:
        raise HTTPException(403, "Separate people must perform reviewer and manager approvals")
    approval.status = "approved" if body.decision == "approve" else "rejected"
    approval.decided_by = user.id
    approval.decided_at = now()
    approval.note = body.note
    if body.decision == "reject":
        invoice.status = "rejected"
        add_timeline(
            db, invoice, "rejected", f"{approval.required_role} rejected version {version.version}"
        )
    else:
        remaining = (
            db.scalar(
                select(func.count(Approval.id)).where(
                    Approval.invoice_version_id == version.id,
                    Approval.status != "approved",
                    Approval.id != approval.id,
                )
            )
            or 0
        )
        if remaining == 0:
            invoice.status = "approved"
        add_timeline(
            db, invoice, "approved", f"{approval.required_role} approved version {version.version}"
        )
    db.commit()
    if invoice.status == "approved":
        background.add_task(
            notify_n8n, get_settings().n8n_approval_webhook_url, invoice.id, version.version
        )
    return {"status": approval.status, "invoice_status": invoice.status}


@portal.post("/invoices/{invoice_id}/retry-posting")
def retry_posting(
    invoice_id: str,
    body: RetryPostingInput,
    background: BackgroundTasks,
    user: User = Depends(operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = request_post_retry(db, invoice_id, user.workspace_id, user.id, body.note)
    background.add_task(notify_n8n, get_settings().n8n_approval_webhook_url, invoice_id)
    return result


@portal.get("/exceptions")
def exceptions(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(
        select(BusinessException)
        .where(BusinessException.workspace_id == user.workspace_id)
        .order_by(BusinessException.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": e.id,
                "invoice_id": e.invoice_id,
                "kind": e.kind,
                "summary": e.summary,
                "status": e.status,
                "created_at": _date(e.created_at),
                "details": e.details,
            }
            for e in rows
        ]
    }


@portal.post("/exceptions/{exception_id}/resolve")
def resolve_exception(
    exception_id: str,
    body: ResolveInput,
    background: BackgroundTasks,
    user: User = Depends(operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    exception = db.scalar(
        select(BusinessException)
        .where(
            BusinessException.id == exception_id,
            BusinessException.workspace_id == user.workspace_id,
        )
        .with_for_update()
    )
    if exception is None:
        raise HTTPException(404, "Exception not found")
    if exception.status != "open":
        raise HTTPException(409, "Exception already resolved")
    invoice = get_invoice(db, exception.invoice_id, user.workspace_id, lock=True)
    if body.resolution == "accept" and exception.kind in {
        "DUPLICATE_IDENTITY",
        "CORRUPTED_DOCUMENT",
        "UNSUPPORTED_CURRENCY",
        "UNCERTAIN_VENDOR",
        "EXTRACTION_REVIEW",
        "CREDIT_NOTE_UNSUPPORTED",
    }:
        raise HTTPException(409, "This finding requires a corrected document or vendor mapping")
    exception.status = body.resolution
    exception.details = {**exception.details, "resolution_note": body.note, "resolved_by": user.id}
    if body.resolution == "reject":
        invoice.status = "rejected"
    elif body.resolution == "accept":
        version = db.scalar(
            select(InvoiceVersion).where(
                InvoiceVersion.invoice_id == invoice.id,
                InvoiceVersion.version == invoice.current_version,
            )
        )
        for finding in db.scalars(
            select(Finding).where(
                Finding.invoice_version_id == version.id, Finding.code == exception.kind
            )
        ).all():
            finding.resolved = True
        remaining = (
            db.scalar(
                select(func.count(Finding.id)).where(
                    Finding.invoice_version_id == version.id,
                    Finding.blocking.is_(True),
                    Finding.resolved.is_(False),
                    Finding.code != exception.kind,
                )
            )
            or 0
        )
        if remaining == 0:
            invoice.status = "validating"
    else:
        invoice.status = "needs_review"
    add_timeline(
        db, invoice, "exception_resolution", f"{exception.kind}: {body.resolution} by {user.role}"
    )
    db.commit()
    if invoice.status == "validating":
        background.add_task(
            notify_n8n,
            get_settings().n8n_resolution_webhook_url,
            invoice.id,
            invoice.current_version,
        )
    return {"status": exception.status, "invoice_status": invoice.status}


@portal.get("/vendors")
def vendors(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(
        select(Vendor).where(Vendor.workspace_id == user.workspace_id).order_by(Vendor.name)
    ).all()
    items = []
    for vendor in rows:
        invoice_count = (
            db.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.vendor_id == vendor.id, Invoice.workspace_id == user.workspace_id
                )
            )
            or 0
        )
        open_count = (
            db.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.vendor_id == vendor.id,
                    Invoice.workspace_id == user.workspace_id,
                    Invoice.status.not_in(["draft_created", "rejected"]),
                )
            )
            or 0
        )
        items.append(
            {
                "id": vendor.id,
                "name": vendor.name,
                "invoice_count": invoice_count,
                "open_count": open_count,
            }
        )
    return {"items": items}


@portal.get("/vendors/{vendor_id}/history")
def vendor_history(
    vendor_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(404, "Vendor not found")
    require_same_workspace(vendor.workspace_id, user)
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.workspace_id == user.workspace_id, Invoice.vendor_id == vendor_id)
        .order_by(Invoice.created_at.desc())
    ).all()
    return {
        "vendor": {
            "id": vendor.id,
            "name": vendor.name,
            "currency": vendor.currency,
            "aliases": vendor.aliases,
        },
        "invoices": [_invoice_summary(db, invoice) for invoice in invoices],
    }


@portal.get("/connectors/health")
def connector_health(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    settings = get_settings()
    n8n_status, n8n_message = "disconnected", "n8n health endpoint unavailable"
    try:
        response = httpx.get("http://n8n:5678/healthz", timeout=2)
        if response.is_success:
            n8n_status, n8n_message = "connected", "n8n health check passed"
    except httpx.HTTPError:
        pass
    items = [
        {
            "name": "n8n",
            "mode": settings.mode,
            "status": n8n_status,
            "last_checked_at": _date(now()),
            "message": n8n_message,
        },
        {
            "name": "PostgreSQL",
            "mode": settings.mode,
            "status": "connected",
            "last_checked_at": _date(now()),
            "message": "Business database query succeeded",
        },
        {
            "name": "Document extraction",
            "mode": settings.mode,
            "status": "connected"
            if settings.mode == "DEMO" or bool(settings.model_id and settings.openai_api_key)
            else "disconnected",
            "last_checked_at": _date(now()),
            "message": "Visible-text local adapter"
            if settings.mode == "DEMO"
            else "Model configured"
            if settings.model_id and settings.openai_api_key
            else "MODEL_ID and OPENAI_API_KEY required",
        },
        {
            "name": "Accounting",
            "mode": settings.mode,
            "status": "connected" if settings.mode == "DEMO" else "pending",
            "last_checked_at": _date(now()),
            "message": "Local simulated draft bills"
            if settings.mode == "DEMO"
            else "Xero OAuth connection requires test organization",
        },
    ]
    return {"items": items}


@portal.get("/digests/latest")
def latest_digest(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    run = db.scalar(
        select(DigestRun)
        .where(DigestRun.workspace_id == user.workspace_id)
        .order_by(DigestRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return {"counts": {}, "created_at": None}
    return {"counts": run.counts, "created_at": _date(run.created_at)}


@portal.post("/replay")
async def replay_upload(
    file: UploadFile = File(), user: User = Depends(operator)
) -> dict[str, Any]:
    settings = get_settings()
    data = await file.read(settings.max_document_bytes + 1)
    if len(data) > settings.max_document_bytes:
        raise HTTPException(413, "File exceeds the 8 MB limit")
    if not (
        (file.content_type == "application/pdf" and data.startswith(b"%PDF-"))
        or (file.content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (file.content_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
    ):
        raise HTTPException(415, "A valid PDF, PNG or JPEG is required")
    event_id = str(uuid4())
    payload = {
        "event_id": event_id,
        "workspace_id": user.workspace_id,
        "source_system": "replay",
        "source_id": event_id,
        "filename": (file.filename or "invoice")[:160],
        "mime_type": file.content_type,
        "content_base64": base64.b64encode(data).decode(),
        "received_at": _date(now()),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                settings.n8n_replay_webhook_url,
                json=payload,
                headers={"X-Internal-Token": settings.internal_token},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            503, "n8n intake is unavailable; retry when connector health is restored"
        ) from exc
    return {"event_id": event_id, "status": "submitted"}


app.include_router(portal)
