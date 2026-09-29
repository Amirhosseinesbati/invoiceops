import base64
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from invoiceops.db import Base, get_db
from invoiceops.main import app
from invoiceops.models import (
    AccountingMapping,
    Approval,
    ApprovalPolicy,
    ArchiveRecord,
    DocumentJob,
    Invoice,
    InvoiceVersion,
    PostingOperation,
    SourceFile,
    TimelineEvent,
    User,
    Vendor,
    Workspace,
    now,
)
from invoiceops.security import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def make_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    return client, sessions, engine


def seed_boundaries(db: Session):
    db.add_all([Workspace(id="a", name="A", mode="DEMO"), Workspace(id="b", name="B", mode="DEMO")])
    db.add_all(
        [
            User(
                id="u-a",
                workspace_id="a",
                name="Operator A",
                email="a@example.com",
                password_hash=hash_password("secret-a"),
                role="operator",
            ),
            User(
                id="u-b",
                workspace_id="b",
                name="Manager B",
                email="b@example.com",
                password_hash=hash_password("secret-b"),
                role="manager",
            ),
        ]
    )
    db.add_all(
        [
            Vendor(id="v-a", workspace_id="a", name="Vendor A", aliases=[], currency="USD"),
            Vendor(id="v-b", workspace_id="b", name="Vendor B", aliases=[], currency="USD"),
            SourceFile(
                id="s-a",
                workspace_id="a",
                path="data/a.pdf",
                mime_type="application/pdf",
                content_hash="a" * 64,
                size_bytes=100,
            ),
            SourceFile(
                id="s-b",
                workspace_id="b",
                path="data/b.pdf",
                mime_type="application/pdf",
                content_hash="b" * 64,
                size_bytes=100,
            ),
        ]
    )
    db.add_all(
        [
            Invoice(
                id="i-a",
                workspace_id="a",
                vendor_id="v-a",
                source_file_id="s-a",
                invoice_number="INV-1",
                po_number="PO-1",
                currency="USD",
                amount=Decimal("129.00"),
                status="awaiting_approval",
                current_version=1,
            ),
            Invoice(
                id="i-b",
                workspace_id="b",
                vendor_id="v-b",
                source_file_id="s-b",
                invoice_number="INV-1",
                po_number="PO-1",
                currency="USD",
                amount=Decimal("129.00"),
                status="received",
                current_version=0,
            ),
        ]
    )
    db.add(
        ApprovalPolicy(
            workspace_id="a", high_amount_threshold=Decimal("1500.00"), tax_rate=Decimal("0.075")
        )
    )
    db.add(
        AccountingMapping(
            workspace_id="a", vendor_id="v-a", accounting_contact_id="SIM-A", expense_account="500"
        )
    )
    db.flush()
    version = InvoiceVersion(
        id="version-a",
        workspace_id="a",
        invoice_id="i-a",
        version=1,
        proposal_hash="proposal-a",
        extraction={
            "vendor_name": "Vendor A",
            "invoice_number": "INV-1",
            "invoice_date": "2026-09-01",
            "due_date": "2026-10-01",
            "line_items": [
                {
                    "sku": "PAPER-A4",
                    "description": "Paper",
                    "quantity": 10,
                    "unit_price": 12,
                    "total": 120,
                }
            ],
        },
        evidence=[],
    )
    db.add(version)
    db.flush()
    db.add(
        Approval(
            id="approval-a",
            workspace_id="a",
            invoice_id="i-a",
            invoice_version_id=version.id,
            proposal_hash=version.proposal_hash,
            required_role="operator",
            status="pending",
            expires_at=now() + timedelta(hours=2),
        )
    )
    db.commit()


def test_workspace_records_are_not_disclosed_and_role_is_checked():
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
        assert client.get("/api/invoices").status_code == 401
        assert (
            client.post(
                "/api/login", json={"username": "a@example.com", "password": "secret-a"}
            ).status_code
            == 200
        )
        listed = client.get("/api/invoices").json()["items"]
        assert [row["id"] for row in listed] == ["i-a"]
        assert client.get("/api/invoices/i-b").status_code == 404
        assert client.get("/api/vendors/v-b/history").status_code == 404
        assert (
            client.post(
                "/api/approvals/approval-a/decide",
                json={"decision": "approve", "proposal_version": 0},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/approvals/approval-a/decide",
                json={"decision": "approve", "proposal_version": 1},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/approvals/approval-a/decide",
                json={"decision": "approve", "proposal_version": 1},
            ).status_code
            == 409
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_signed_source_preview_renders_only_authorized_page(tmp_path, monkeypatch):
    from invoiceops.config import get_settings
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "invoice.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    pdf.drawString(72, 720, "INVOICE INV-1")
    pdf.save()
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            db.get(SourceFile, "s-a").path = str(pdf_path)
            db.commit()
        assert client.post(
            "/api/login", json={"username": "a@example.com", "password": "secret-a"}
        ).status_code == 200
        signed_url = client.get("/api/invoices/i-a").json()["source_url"]
        preview = client.get(f"{signed_url}&preview_page=1")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"
        assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert client.get(f"{signed_url}&preview_page=2").status_code == 404
        assert client.get(f"{signed_url}&preview_page=101").status_code == 400
        assert client.get(signed_url.replace("sig=", "sig=invalid")).status_code == 403
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_timeout_after_accepted_write_reconciles_to_single_draft():
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            invoice = db.get(Invoice, "i-a")
            invoice.status = "approved"
            invoice.simulator_outcome = "timeout"
            approval = db.get(Approval, "approval-a")
            approval.status = "approved"
            approval.decided_by = "u-a"
            approval.decided_at = now()
            db.commit()
        from invoiceops.config import get_settings

        headers = {"X-Internal-Token": get_settings().internal_token}
        claim = client.post(
            "/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers
        ).json()
        assert claim["claimed"] is True
        assert (
            client.post("/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers).json()[
                "claimed"
            ]
            is False
        )
        result = client.post(
            "/sim/accounting/bills",
            json={
                key: claim[key]
                for key in (
                    "operation_key",
                    "workspace_id",
                    "vendor_id",
                    "invoice_number",
                    "amount",
                    "currency",
                    "bill_payload",
                )
            },
            headers=headers,
        )
        assert result.status_code == 504
        client.post(
            "/internal/post/result",
            json={
                "operation_id": claim["operation_id"],
                "attempt": claim["attempt"],
                "status": "uncertain",
                "error": "timeout",
            },
            headers=headers,
        )
        found = client.get(
            f"/sim/accounting/bills/by-operation/{claim['operation_key']}", headers=headers
        ).json()
        assert found["found"] is True
        resolved = client.post(
            "/internal/reconcile/result",
            json={"operation_id": claim["operation_id"], **found},
            headers=headers,
        ).json()
        assert resolved["status"] == "draft_created"
        replay = client.post(
            "/sim/accounting/bills",
            json={
                key: claim[key]
                for key in (
                    "operation_key",
                    "workspace_id",
                    "vendor_id",
                    "invoice_number",
                    "amount",
                    "currency",
                    "bill_payload",
                )
            },
            headers=headers,
        ).json()
        assert replay["accounting_id"] == found["accounting_id"]
        with sessions() as db:
            from invoiceops.models import SimulatedBill

            assert len(db.query(SimulatedBill).all()) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_simulator_rejects_changes_to_claimed_approved_bill():
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            db.get(Invoice, "i-a").status = "approved"
            approval = db.get(Approval, "approval-a")
            approval.status = "approved"
            approval.decided_by = "u-a"
            approval.decided_at = now()
            db.commit()
        from invoiceops.config import get_settings

        headers = {"X-Internal-Token": get_settings().internal_token}
        claim = client.post(
            "/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers
        ).json()
        assert claim["claimed"] is True
        bill = {
            key: claim[key]
            for key in (
                "operation_key",
                "workspace_id",
                "vendor_id",
                "invoice_number",
                "amount",
                "currency",
                "bill_payload",
            )
        }
        assert (
            client.post(
                "/sim/accounting/bills", json={**bill, "currency": "EUR"}, headers=headers
            ).status_code
            == 409
        )
        altered_payload = {
            **bill["bill_payload"],
            "LineItems": [{**bill["bill_payload"]["LineItems"][0], "UnitAmount": 1}],
        }
        assert (
            client.post(
                "/sim/accounting/bills",
                json={**bill, "bill_payload": altered_payload},
                headers=headers,
            ).status_code
            == 409
        )
        lookup = client.get(
            f"/sim/accounting/bills/by-operation/{claim['operation_key']}", headers=headers
        ).json()
        assert lookup["found"] is False
        assert client.post("/sim/accounting/bills", json=bill, headers=headers).status_code == 201
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_credential_failure_records_operator_action_without_draft():
    from invoiceops.config import get_settings
    from invoiceops.models import BusinessException, SimulatedBill

    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            invoice = db.get(Invoice, "i-a")
            invoice.status = "approved"
            invoice.simulator_outcome = "credential_error"
            approval = db.get(Approval, "approval-a")
            approval.status = "approved"
            approval.decided_by = "u-a"
            approval.decided_at = now()
            db.commit()
        headers = {"X-Internal-Token": get_settings().internal_token}
        claim = client.post(
            "/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers
        ).json()
        bill = {
            key: claim[key]
            for key in (
                "operation_key", "workspace_id", "vendor_id", "invoice_number",
                "amount", "currency", "bill_payload",
            )
        }
        response = client.post("/sim/accounting/bills", json=bill, headers=headers)
        assert response.status_code == 401
        assert "credential" in response.json()["error"].lower()
        recorded = client.post(
            "/internal/post/result",
            json={
                "operation_id": claim["operation_id"],
                "attempt": claim["attempt"],
                "status": "credential_error",
                "error": response.json()["error"],
            },
            headers=headers,
        )
        assert recorded.json()["status"] == "failed"
        with sessions() as db:
            assert not db.query(SimulatedBill).all()
            exception = db.query(BusinessException).one()
            assert exception.kind == "ACCOUNTING_FAILURE"
            assert "credential" in exception.summary.lower()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_orphaned_claim_requires_lookup_and_operator_before_retry(monkeypatch, tmp_path):
    client, sessions, engine = make_client()
    try:
        from invoiceops.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "data_dir", tmp_path)

        async def no_notification(*_args, **_kwargs):
            return None

        monkeypatch.setattr("invoiceops.main.notify_n8n", no_notification)
        with sessions() as db:
            seed_boundaries(db)
            invoice = db.get(Invoice, "i-a")
            invoice.status = "approved"
            approval = db.get(Approval, "approval-a")
            approval.status = "approved"
            approval.decided_by = "u-a"
            approval.decided_at = now()
            db.commit()
        headers = {"X-Internal-Token": settings.internal_token}
        first = client.post(
            "/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers
        ).json()
        assert first["claimed"] is True and first["attempt"] == 1
        assert (
            client.post(
                "/internal/intake",
                json={
                    "workspace_id": "a",
                    "source_system": "replay",
                    "source_id": "new-revision",
                    "revision_of": "i-a",
                    "filename": "new.pdf",
                    "mime_type": "application/pdf",
                    "content_base64": base64.b64encode(b"%PDF-1.4\n%%EOF").decode(),
                },
                headers=headers,
            ).status_code
            == 409
        )
        with sessions() as db:
            operation = db.get(PostingOperation, first["operation_id"])
            operation.updated_at = now() - timedelta(minutes=5)
            db.commit()
        uncertain = client.get("/internal/reconcile/uncertain", headers=headers).json()
        assert uncertain == [
            {
                "operation_id": first["operation_id"],
                "operation_key": first["operation_key"],
                "invoice_id": "i-a",
            }
        ]
        assert (
            client.post("/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers).json()[
                "claimed"
            ]
            is False
        )
        assert (
            client.post(
                "/api/invoices/i-a/retry-posting", json={"note": "Please retry"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/login", json={"username": "a@example.com", "password": "secret-a"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/invoices/i-a/retry-posting", json={"note": "Premature retry"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/internal/reconcile/result",
                json={"operation_id": first["operation_id"], "found": True},
                headers=headers,
            ).status_code
            == 422
        )
        lookup = client.get(
            f"/sim/accounting/bills/by-operation/{first['operation_key']}", headers=headers
        ).json()
        assert lookup == {"found": False, "accounting_id": None}
        absent = client.post(
            "/internal/reconcile/result",
            json={"operation_id": first["operation_id"], **lookup},
            headers=headers,
        ).json()
        assert absent["status"] == "failed"
        with sessions() as db:
            assert db.get(PostingOperation, first["operation_id"]).status == "reconciled_absent"
        monkeypatch.setattr(settings, "accounting_provider", "xero")
        assert (
            client.post(
                "/api/invoices/i-a/retry-posting",
                json={"note": "Connected retries require a new provider key"},
            ).status_code
            == 409
        )
        monkeypatch.setattr(settings, "accounting_provider", "demo")
        requested = client.post(
            "/api/invoices/i-a/retry-posting",
            json={"note": "Lookup confirmed no draft"},
        )
        assert requested.status_code == 200
        assert requested.json()["status"] == "retry_requested"
        assert client.get("/internal/recovery/pending-postings", headers=headers).json() == [
            {"invoice_id": "i-a"}
        ]
        second = client.post(
            "/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers
        ).json()
        assert second["claimed"] is True and second["attempt"] == 2
        assert second["operation_id"] == first["operation_id"]
        assert (
            client.post(
                "/internal/post/result",
                json={"operation_id": first["operation_id"], "attempt": 1, "status": "uncertain"},
                headers=headers,
            ).status_code
            == 409
        )
        bill = client.post(
            "/sim/accounting/bills",
            json={
                key: second[key]
                for key in (
                    "operation_key",
                    "workspace_id",
                    "vendor_id",
                    "invoice_number",
                    "amount",
                    "currency",
                    "bill_payload",
                )
            },
            headers=headers,
        )
        assert bill.status_code == 201
        result = client.post(
            "/internal/post/result",
            json={
                "operation_id": second["operation_id"],
                "attempt": second["attempt"],
                "status": "accepted",
                "accounting_id": bill.json()["accounting_id"],
            },
            headers=headers,
        )
        assert result.json()["status"] == "draft_created"
        assert client.get("/internal/recovery/pending-archives", headers=headers).json() == [
            {"invoice_id": "i-a"}
        ]
        assert client.post("/internal/invoices/i-a/archive", headers=headers).status_code == 200
        assert client.get("/internal/recovery/pending-archives", headers=headers).json() == []
        with sessions() as db:
            assert db.query(ArchiveRecord).count() == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_duplicate_completion_keeps_posted_invoice_state():
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            invoice = db.get(Invoice, "i-a")
            invoice.status = "draft_created"
            invoice.accounting_id = "SIM-EXISTING"
            version = db.get(InvoiceVersion, "version-a")
            version.extraction = {**version.extraction, "job_id": "job-a"}
            db.add(
                DocumentJob(
                    id="job-a",
                    workspace_id="a",
                    invoice_id="i-a",
                    source_file_id="s-a",
                    status="completed",
                    result={"extraction": version.extraction},
                )
            )
            db.commit()
            old_events = db.query(TimelineEvent).count()
        from invoiceops.config import get_settings

        headers = {"X-Internal-Token": get_settings().internal_token}
        validated = client.post(
            "/internal/invoices/i-a/validate", json={"job_id": "job-a"}, headers=headers
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "draft_created"
        routed = client.post(
            "/internal/invoices/i-a/route",
            json={"route": "reviewer", "validation_version": 1},
            headers=headers,
        )
        assert routed.status_code == 200
        assert routed.json()["status"] == "draft_created"
        with sessions() as db:
            assert db.get(Invoice, "i-a").status == "draft_created"
            assert db.query(Approval).count() == 1
            assert db.query(TimelineEvent).count() == old_events
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_old_job_cannot_validate_or_fail_a_revised_source():
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            db.add(
                SourceFile(
                    id="s-revision",
                    workspace_id="a",
                    path="data/revision.pdf",
                    mime_type="application/pdf",
                    content_hash="c" * 64,
                    size_bytes=100,
                )
            )
            db.add(
                DocumentJob(
                    id="job-old",
                    workspace_id="a",
                    invoice_id="i-a",
                    source_file_id="s-a",
                    status="completed",
                    result={"extraction": {"invoice_number": "INV-OLD"}},
                )
            )
            invoice = db.get(Invoice, "i-a")
            invoice.source_file_id = "s-revision"
            invoice.status = "extracting"
            db.commit()
        from invoiceops.config import get_settings

        headers = {"X-Internal-Token": get_settings().internal_token}
        validated = client.post(
            "/internal/invoices/i-a/validate", json={"job_id": "job-old"}, headers=headers
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "stale"
        failed = client.post(
            "/internal/invoices/i-a/processing-failed",
            json={"job_id": "job-old", "reason": "old_job_failed"},
            headers=headers,
        )
        assert failed.status_code == 200
        assert failed.json()["status"] == "stale"
        with sessions() as db:
            invoice = db.get(Invoice, "i-a")
            assert invoice.status == "extracting"
            assert invoice.current_version == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_xero_draft_check_requires_approved_identity_and_amount():
    client, sessions, engine = make_client()
    try:
        with sessions() as db:
            seed_boundaries(db)
            invoice = db.get(Invoice, "i-a")
            invoice.status = "approved"
            approval = db.get(Approval, "approval-a")
            approval.status = "approved"
            approval.decided_by = "u-a"
            approval.decided_at = now()
            version = db.get(InvoiceVersion, "version-a")
            version.extraction = {**version.extraction, "subtotal": 120, "tax": 9}
            db.commit()
        from invoiceops.config import get_settings

        headers = {"X-Internal-Token": get_settings().internal_token}
        claim = client.post(
            "/internal/post/claim", json={"invoice_id": "i-a"}, headers=headers
        ).json()
        draft = {
            "InvoiceID": "XERO-ONE",
            "Type": "ACCPAY",
            "Status": "DRAFT",
            "InvoiceNumber": "INV-1",
            "CurrencyCode": "USD",
            "Contact": {"ContactID": "SIM-A"},
            "SubTotal": 120,
            "TotalTax": 9,
            "Total": 129,
        }
        checked = client.post(
            "/internal/xero/draft-check",
            json={"operation_id": claim["operation_id"], "attempt": 1, "invoice": draft},
            headers=headers,
        ).json()
        assert checked == {"match": True, "accounting_id": "XERO-ONE", "reason": None}
        mismatched = client.post(
            "/internal/xero/draft-check",
            json={
                "operation_id": claim["operation_id"],
                "attempt": 1,
                "invoice": {**draft, "TotalTax": 0},
            },
            headers=headers,
        ).json()
        assert mismatched["match"] is False
        with sessions() as db:
            assert db.get(PostingOperation, claim["operation_id"]).status == "claimed"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
