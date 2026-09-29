"""Send three real synthetic invoice PDFs to the local GreenMail sandbox.

The clean invoice is sent first. Follow-ups need an explicit operator gate so the
business-identity duplicate cannot race the original invoice's validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
DEMO_TO = "ap@invoiceops.test"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}\Z")


def dataset_path(value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def pdf_bytes(dataset: Path, invoice: dict[str, Any]) -> bytes:
    relative = invoice.get("document_path")
    if not isinstance(relative, str) or not relative.lower().endswith(".pdf"):
        raise ValueError(f"{invoice.get('id')}: expected a PDF document_path")
    path = (dataset / relative).resolve()
    try:
        path.relative_to(dataset)
    except ValueError as exc:
        raise ValueError(f"{invoice.get('id')}: document path leaves dataset") from exc
    if not path.is_file():
        raise FileNotFoundError(f"{invoice.get('id')}: missing generated PDF: {path}")
    content = path.read_bytes()
    if not content.startswith(b"%PDF-") or len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{invoice.get('id')}: PDF signature or 8 MiB limit failed")
    source_hash = invoice.get("source_hash")
    if source_hash and hashlib.sha256(content).hexdigest() != source_hash:
        raise ValueError(f"{invoice.get('id')}: generated PDF hash differs from public manifest")
    return content


def select_triplet(dataset: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = dataset / "public" / "invoices.json"
    invoices = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(invoices, list):
        raise ValueError("public/invoices.json must contain a list")
    by_id = {row["id"]: row for row in invoices}
    if len(by_id) != len(invoices):
        raise ValueError("public/invoices.json has repeated invoice IDs")

    candidates = []
    for duplicate in invoices:
        if duplicate.get("exception_type") != "duplicate_identity":
            continue
        original = by_id.get(duplicate.get("revision_of_invoice_id"))
        if not original or original.get("exception_type") is not None:
            continue
        if original.get("document_kind") != "invoice":
            continue
        if (original.get("vendor_id"), original.get("invoice_number")) != (
            duplicate.get("vendor_id"), duplicate.get("invoice_number")
        ):
            continue
        if not original.get("source_hash") or original["source_hash"] == duplicate.get("source_hash"):
            continue
        candidates.append((original, duplicate))
    if not candidates:
        raise ValueError("no clean original with a distinct-PDF duplicate_identity revision")
    # Prefer text PDFs for the live demo, while allowing the fast fixture's scanned duplicate.
    candidates.sort(key=lambda pair: (bool(pair[0].get("is_scanned")) + bool(pair[1].get("is_scanned")), pair[1]["id"]))
    original, duplicate = candidates[0]

    mismatches = [
        row for row in invoices
        if row.get("exception_type") == "price_mismatch"
        and (row.get("vendor_id"), row.get("invoice_number"))
        != (original.get("vendor_id"), original.get("invoice_number"))
    ]
    if not mismatches:
        raise ValueError("no separate price_mismatch invoice in public manifest")
    mismatches.sort(key=lambda row: (bool(row.get("is_scanned")), row["id"]))
    mismatch = mismatches[0]
    for invoice in (original, duplicate, mismatch):
        pdf_bytes(dataset, invoice)
    return original, duplicate, mismatch


def build_message(invoice: dict[str, Any], scenario: str, run_id: str, dataset: Path) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"Synthetic Vendor <{invoice['vendor_id']}@vendors.invoiceops.test>"
    message["To"] = DEMO_TO
    message["Subject"] = f"InvoiceOps demo {scenario}: {invoice['invoice_number']}"
    message["Date"] = format_datetime(datetime.now(UTC))
    message["Message-ID"] = f"<invoiceops-demo-{run_id}-{scenario}@invoiceops.test>"
    message["X-InvoiceOps-Demo-Run"] = run_id
    message["X-InvoiceOps-Demo-Scenario"] = scenario
    message["X-InvoiceOps-Demo-Invoice-ID"] = invoice["id"]
    message.set_content("Synthetic invoice attachment for the local InvoiceOps demo. No payment is requested.")
    message.add_attachment(
        pdf_bytes(dataset, invoice),
        maintype="application",
        subtype="pdf",
        filename=Path(invoice["document_path"]).name,
    )
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="generated/invoiceops_fast", help="Generated dataset directory")
    parser.add_argument("--stage", required=True, choices=("clean", "followups"))
    parser.add_argument("--run-id", help="Reuse the clean stage's run ID for follow-ups")
    parser.add_argument(
        "--original-ready", action="store_true",
        help="Operator confirms the clean invoice reached validation before sending follow-ups",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and show selection without SMTP")
    parser.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3025)
    args = parser.parse_args()
    if args.stage == "followups" and not args.run_id:
        parser.error("--stage followups requires the --run-id printed by the clean stage")
    if args.stage == "followups" and not (args.original_ready or args.dry_run):
        parser.error("followups require --original-ready after checking the clean invoice in n8n/API")
    run_id = args.run_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    if not RUN_ID_PATTERN.fullmatch(run_id):
        parser.error("--run-id must be 1-64 letters, digits, or hyphens")
    dataset = dataset_path(args.dataset)
    original, duplicate, mismatch = select_triplet(dataset)
    selected = (("clean", original),) if args.stage == "clean" else (
        ("duplicate_identity", duplicate), ("price_mismatch", mismatch)
    )
    messages = [(scenario, invoice, build_message(invoice, scenario, run_id, dataset)) for scenario, invoice in selected]
    print(f"Run ID: {run_id}")
    print(f"Business identity: {original['vendor_id']} / {original['invoice_number']}")
    for scenario, invoice, message in messages:
        print(f"{scenario}: {invoice['id']} | {Path(invoice['document_path']).name} | {message['Message-ID']}")
    if args.dry_run:
        print("Dry run: no mail sent.")
        return 0

    password = os.environ.get("INVOICEOPS_DEMO_MAIL_PASSWORD", "demo-mail")
    with smtplib.SMTP(args.host, args.port, timeout=15) as smtp:
        smtp.ehlo()
        smtp.login("ap", password)
        for scenario, invoice, message in messages:
            smtp.send_message(message, from_addr=message["From"].addresses[0].addr_spec, to_addrs=[DEMO_TO])
            print(f"Sent {scenario}: {invoice['id']}")
    if args.stage == "clean":
        print("Wait until the clean invoice reaches validation, then send follow-ups with --original-ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
