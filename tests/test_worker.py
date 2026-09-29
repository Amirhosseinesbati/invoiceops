"""The worker must preserve queued work and recover expired leases."""

from datetime import timedelta

from invoiceops import worker
from invoiceops.db import Base
from invoiceops.models import DocumentJob, Invoice, SourceFile, Workspace, now
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_expiry_only_fails_exhausted_running_lease(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    old = now() - timedelta(minutes=10)
    try:
        with sessions() as db:
            db.add(Workspace(id="workspace", name="Workspace", mode="DEMO"))
            db.add(
                SourceFile(
                    id="source",
                    workspace_id="workspace",
                    path="unused.pdf",
                    mime_type="application/pdf",
                    content_hash="a" * 64,
                    size_bytes=1,
                )
            )
            db.add(
                Invoice(
                    id="invoice",
                    workspace_id="workspace",
                    source_file_id="source",
                    status="extracting",
                )
            )
            for job_id, status, attempts in (
                ("queued", "queued", 0),
                ("recoverable", "running", 1),
                ("exhausted", "running", 3),
            ):
                db.add(
                    DocumentJob(
                        id=job_id,
                        workspace_id="workspace",
                        invoice_id="invoice",
                        source_file_id="source",
                        status=status,
                        attempts=attempts,
                        created_at=old,
                        lease_until=old,
                    )
                )
            db.commit()

        worker.expire_old_jobs()

        with sessions() as db:
            assert db.get(DocumentJob, "queued").status == "queued"
            assert db.get(DocumentJob, "recoverable").status == "running"
            expired = db.get(DocumentJob, "exhausted")
            assert expired.status == "failed"
            assert expired.failure_reason == "deadline_exceeded"
            assert expired.lease_until is None
    finally:
        engine.dispose()
