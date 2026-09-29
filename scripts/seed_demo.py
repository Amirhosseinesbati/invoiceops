"""Seed reference data and two isolated demo workspaces; invoices enter through n8n."""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from invoiceops.config import get_settings  # noqa: E402
from invoiceops.db import SessionLocal  # noqa: E402
from invoiceops.models import (  # noqa: E402
    AccountingMapping,
    ApprovalPolicy,
    Invoice,
    PurchaseOrder,
    Receipt,
    SourceFile,
    User,
    Vendor,
    Workspace,
)
from invoiceops.security import hash_password  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC)


def seed(source_dir: Path) -> dict[str, int]:
    public = source_dir / "public"
    if not public.is_dir():
        raise SystemExit(f"Generate the dataset first: missing {public}")
    settings = get_settings()
    counts = {"workspaces": 0, "users": 0, "vendors": 0, "purchase_orders": 0, "receipts": 0}
    with SessionLocal() as db:
        for workspace_id, name in (
            ("demo-a", "Northstar Distribution"),
            ("demo-b", "Bluewater Supplies"),
        ):
            if db.get(Workspace, workspace_id) is None:
                db.add(Workspace(id=workspace_id, name=name, mode="DEMO"))
                counts["workspaces"] += 1
        db.flush()
        users = [
            ("operator@example.com", "Demo Operator", "operator", "demo-a", "demo-operator"),
            ("manager@example.com", "Demo Manager", "manager", "demo-a", "demo-manager"),
            ("viewer@example.com", "Demo Viewer", "viewer", "demo-a", "demo-viewer"),
            (
                "operator-b@example.com",
                "Workspace B Operator",
                "operator",
                "demo-b",
                "demo-operator-b",
            ),
        ]
        for email, name, role, workspace, password in users:
            if db.scalar(select(User.id).where(User.email == email)) is None:
                db.add(
                    User(
                        email=email,
                        name=name,
                        role=role,
                        workspace_id=workspace,
                        password_hash=hash_password(password),
                    )
                )
                counts["users"] += 1
        for workspace_id in ("demo-a", "demo-b"):
            if (
                db.scalar(
                    select(ApprovalPolicy.id).where(ApprovalPolicy.workspace_id == workspace_id)
                )
                is None
            ):
                db.add(
                    ApprovalPolicy(
                        workspace_id=workspace_id,
                        high_amount_threshold=Decimal("1500.00"),
                        tax_rate=Decimal("0.075"),
                        currency="USD",
                        ttl_hours=72,
                    )
                )
        for row in read_json(public / "vendors.json"):
            if db.get(Vendor, row["id"]) is None:
                db.add(
                    Vendor(
                        id=row["id"],
                        workspace_id="demo-a",
                        name=row["legal_name"],
                        aliases=row.get("aliases", []),
                        tax_id=row.get("tax_id"),
                        currency=row.get("currency", "USD"),
                    )
                )
                db.flush()
                db.add(
                    AccountingMapping(
                        workspace_id="demo-a",
                        vendor_id=row["id"],
                        accounting_contact_id=f"SIM-CONTACT-{row['id']}",
                        expense_account="500",
                    )
                )
                counts["vendors"] += 1
        for row in read_json(public / "purchase_orders.json"):
            if db.get(PurchaseOrder, row["id"]) is None:
                db.add(
                    PurchaseOrder(
                        id=row["id"],
                        workspace_id="demo-a",
                        vendor_id=row["vendor_id"],
                        number=row["number"],
                        currency=row["currency"],
                        lines=row.get("line_items", []),
                        document_path=row.get("document_path"),
                    )
                )
                counts["purchase_orders"] += 1
        db.flush()
        for row in read_json(public / "receipts.json"):
            if db.get(Receipt, row["id"]) is None:
                db.add(
                    Receipt(
                        id=row["id"],
                        workspace_id="demo-a",
                        po_id=row["po_id"],
                        lines=row.get("line_items", []),
                        received_at=parse_date(row["received_at"]),
                    )
                )
                counts["receipts"] += 1
        if db.get(Vendor, "b-vendor-001") is None:
            db.add(
                Vendor(
                    id="b-vendor-001",
                    workspace_id="demo-b",
                    name="Bluewater Office Goods",
                    aliases=[],
                    tax_id="TEST-B-001",
                    currency="USD",
                )
            )
            db.flush()
            db.add(
                AccountingMapping(
                    workspace_id="demo-b",
                    vendor_id="b-vendor-001",
                    accounting_contact_id="SIM-CONTACT-B-001",
                    expense_account="500",
                )
            )
            counts["vendors"] += 1
        if db.get(PurchaseOrder, "b-po-001") is None:
            db.add(
                PurchaseOrder(
                    id="b-po-001",
                    workspace_id="demo-b",
                    vendor_id="b-vendor-001",
                    number="BW-PO-001",
                    currency="USD",
                    lines=[
                        {
                            "sku": "PAPER-A4",
                            "description": "Paper ream",
                            "quantity": 10,
                            "unit_price": 12,
                            "total": 120,
                        }
                    ],
                )
            )
            db.flush()
            counts["purchase_orders"] += 1
        if db.get(Receipt, "b-receipt-001") is None:
            db.add(
                Receipt(
                    id="b-receipt-001",
                    workspace_id="demo-b",
                    po_id="b-po-001",
                    lines=[{"sku": "PAPER-A4", "received_quantity": 10}],
                    received_at=datetime.now(UTC),
                )
            )
            counts["receipts"] += 1
        first = read_json(public / "invoices.json")[0]
        source_path = source_dir / first["document_path"]
        source_bytes = source_path.read_bytes()
        digest = hashlib.sha256(source_bytes).hexdigest()
        target = settings.data_dir / "uploads" / "demo-b" / f"{digest}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source_path, target)
        if db.get(SourceFile, "b-source-001") is None:
            db.add(
                SourceFile(
                    id="b-source-001",
                    workspace_id="demo-b",
                    path=str(target),
                    mime_type="application/pdf",
                    content_hash=digest,
                    size_bytes=len(source_bytes),
                )
            )
            db.flush()
        if db.get(Invoice, "b-invoice-001") is None:
            db.add(
                Invoice(
                    id="b-invoice-001",
                    workspace_id="demo-b",
                    source_file_id="b-source-001",
                    vendor_id="b-vendor-001",
                    invoice_number="BW-INV-001",
                    po_number="BW-PO-001",
                    amount=Decimal("120.00"),
                    currency="USD",
                    status="received",
                )
            )
        db.commit()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=ROOT / "generated" / "invoiceops_fast")
    args = parser.parse_args()
    print(json.dumps(seed(args.source_dir.resolve()), indent=2))
