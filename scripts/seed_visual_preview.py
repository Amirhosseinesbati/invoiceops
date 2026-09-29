"""Create a local SQLite UI preview; this does not validate n8n integration."""

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "preview.sqlite3"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.as_posix()
os.environ["DATA_DIR"] = str(ROOT / "data" / "preview-files")
os.environ["ENABLE_WORKER"] = "false"
os.environ["MODE"] = "DEMO"
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

from invoiceops.business import receive_event, route_invoice, validate_invoice  # noqa: E402
from invoiceops.db import Base, SessionLocal, engine  # noqa: E402
from invoiceops.extraction import SCHEMA_VERSION, _page_texts, parse_visible_invoice  # noqa: E402
from invoiceops.models import DocumentJob  # noqa: E402

from scripts.seed_demo import seed  # noqa: E402


def main() -> None:
    source_dir = ROOT / "generated" / "invoiceops_fast"
    Base.metadata.create_all(engine)
    seed(source_dir)
    invoices = json.loads((source_dir / "public" / "invoices.json").read_text(encoding="utf-8"))
    created = 0
    for row in invoices[:18]:
        path = source_dir / row["document_path"]
        if row.get("is_scanned") or not path.exists():
            continue
        pages, warnings = _page_texts(path)
        try:
            extraction = parse_visible_invoice(pages).model_dump()
        except Exception:
            continue
        payload = {
            "workspace_id": "demo-a",
            "source_system": "replay",
            "source_id": f"visual-preview-{row['id']}",
            "filename": path.name,
            "mime_type": "application/pdf",
            "content_base64": base64.b64encode(path.read_bytes()).decode(),
        }
        with SessionLocal() as db:
            intake = receive_event(db, payload)
            if intake["duplicate"]:
                continue
            job = DocumentJob(
                workspace_id="demo-a",
                invoice_id=intake["invoice_id"],
                source_file_id=intake["source_file_id"],
                status="completed",
                progress=100,
                result={
                    "schema_version": SCHEMA_VERSION,
                    "source_hash": intake["source_hash"],
                    "extraction_version": 1,
                    "extraction": extraction,
                    "warnings": warnings,
                    "validation_findings": [],
                    "evidence": extraction["evidence"],
                },
            )
            db.add(job)
            db.commit()
            result = validate_invoice(db, intake["invoice_id"], job.id)
            route_invoice(db, intake["invoice_id"], result["route"], result["validation_version"])
            created += 1
    print(f"Visual-only preview seeded {created} extracted invoices at {DB_PATH}")


if __name__ == "__main__":
    main()
