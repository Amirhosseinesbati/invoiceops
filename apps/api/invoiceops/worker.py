"""A leased PostgreSQL job worker; safe to restart while extraction is pending."""

import logging
import threading
from datetime import timedelta

import httpx
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import or_, select

from invoiceops.config import get_settings
from invoiceops.db import SessionLocal
from invoiceops.extraction import SCHEMA_VERSION, make_graph
from invoiceops.models import DocumentJob, SourceFile, now

log = logging.getLogger(__name__)
STOP = threading.Event()
THREAD: threading.Thread | None = None


def expire_old_jobs() -> None:
    # Waiting in the queue does not consume an extraction attempt. A crashed
    # worker's expired lease is retried until its third attempt is exhausted.
    with SessionLocal() as db:
        jobs = db.scalars(
            select(DocumentJob).where(
                DocumentJob.status == "running",
                DocumentJob.attempts >= 3,
                DocumentJob.lease_until < now(),
            )
        ).all()
        for job in jobs:
            job.status = "failed"
            job.failure_reason = "deadline_exceeded"
            job.lease_until = None
        db.commit()


def run_one(graph: object) -> bool:
    expire_old_jobs()
    with SessionLocal() as db:
        job = db.scalar(
            select(DocumentJob)
            .where(
                DocumentJob.cancelled.is_(False),
                or_(
                    DocumentJob.status == "queued",
                    (DocumentJob.status == "running") & (DocumentJob.lease_until < now()),
                ),
            )
            .order_by(DocumentJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return False
        source = db.get(SourceFile, job.source_file_id)
        job.status = "running"
        job.progress = 10
        job.lease_until = now() + timedelta(seconds=90)
        job.attempts += 1
        db.commit()
        job_id, source_path, source_hash = job.id, source.path, source.content_hash
    try:
        result = graph.invoke(
            {"source_path": source_path, "source_hash": source_hash},
            config={"configurable": {"thread_id": job_id}, "recursion_limit": 10},
        )
        status = result.get("status", "error")
        with SessionLocal() as db:
            job = db.get(DocumentJob, job_id)
            if job.cancelled:
                job.status = "cancelled"
            elif status in {"completed", "review"}:
                job.status = status
                job.progress = 100
                job.result = {
                    "schema_version": SCHEMA_VERSION,
                    "source_hash": source_hash,
                    "extraction_version": 1,
                    "extraction": result.get("extracted", {}),
                    "evidence": result.get("extracted", {}).get("evidence", []),
                    "validation_findings": result.get("findings", []),
                    "warnings": result.get("warnings", []),
                }
            else:
                job.status = "failed"
                job.failure_reason = result.get("error", "Extraction failed")[:500]
            job.lease_until = None
            db.commit()
        try:
            httpx.post(
                get_settings().n8n_job_complete_webhook_url,
                json={"job_id": job_id, "invoice_id": job.invoice_id},
                headers={"X-Internal-Token": get_settings().internal_token},
                timeout=5,
            ).raise_for_status()
        except httpx.HTTPError:
            log.warning("job_callback_unavailable job_id=%s; schedule will recover", job_id)
    except Exception as exc:
        log.exception("document_job_failed", extra={"job_id": job_id})
        with SessionLocal() as db:
            job = db.get(DocumentJob, job_id)
            if job.attempts >= 3:
                job.status = "failed"
                job.failure_reason = type(exc).__name__
                job.lease_until = None
            else:
                job.status = "queued"
                job.lease_until = None
            db.commit()
    return True


def worker_loop() -> None:
    settings = get_settings()
    with PostgresSaver.from_conn_string(settings.checkpoint_url) as checkpointer:
        checkpointer.setup()
        graph = make_graph(settings, checkpointer)
        while not STOP.is_set():
            try:
                if not run_one(graph):
                    STOP.wait(2)
            except Exception:
                log.exception("worker_loop_failed")
                STOP.wait(5)


def start_worker() -> None:
    global THREAD
    STOP.clear()
    THREAD = threading.Thread(target=worker_loop, name="invoiceops-extraction-worker", daemon=True)
    THREAD.start()


def stop_worker() -> None:
    STOP.set()
    if THREAD:
        THREAD.join(timeout=5)
