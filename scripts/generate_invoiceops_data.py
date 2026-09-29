"""Reproducible, synthetic InvoiceOps documents and operational scenarios.

The public manifest is for seeding procurement and intake simulators. The private
labels are for offline evaluation only; never mount them into the extractor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

DEFAULT_SEED = 10410
DEFAULT_REFERENCE_DATE = "2026-09-28"
SCHEMA_VERSION = "invoiceops.synthetic.v1"
CENT = Decimal("0.01")
TAX_RATE = Decimal("0.075")
APPROVAL_THRESHOLD = Decimal("1500.00")
LAYOUT_NAMES = (
    "classic_grid",
    "sidebar_summary",
    "compact_ledger",
    "header_band",
    "boxed_totals",
    "minimal_statement",
    "warehouse_slip",
    "modern_split",
)
VENDOR_NAMES = (
    "Harborline Components",
    "Harborline Trading",
    "North Ridge Parts",
    "Blue Acre Industrial",
    "Cobalt Supply House",
    "Mason Creek Packaging",
    "Westhaven Fasteners",
    "Aster Paper Goods",
    "Copperfield Wholesale",
    "Fable Creek Hardware",
    "Juniper Bay Logistics",
    "Ironleaf Plastics",
    "Morrow Office Supply",
    "Pinebridge Textiles",
    "Orion Valve Company",
    "Red Fern Electronics",
    "Silvertrail Tools",
    "Granite Peak Safety",
)
PRODUCTS = (
    ("BX-110", "Corrugated shipping boxes", "18.40"),
    ("FL-220", "Pallet stretch film", "46.75"),
    ("LB-330", "Thermal carton labels", "31.20"),
    ("TP-440", "Reinforced packing tape", "12.90"),
    ("GL-550", "Nitrile handling gloves", "22.50"),
    ("PC-660", "Protective corner guards", "16.15"),
    ("PK-770", "Foam packing inserts", "54.30"),
    ("ST-880", "Steel shelf brackets", "73.80"),
    ("CT-990", "Reusable storage crates", "119.00"),
    ("RF-101", "Reflective safety rolls", "39.65"),
)
EXCEPTION_COUNTS = {
    "missing_po": 6,
    "uncertain_vendor": 6,
    "corrupted_document": 6,
    "duplicate_identity": 7,
    "inconsistent_total": 7,
    "price_mismatch": 7,
    "quantity_mismatch": 7,
    "tax_mismatch": 5,
    "unsupported_currency": 4,
    "credit_note": 5,
}
FAST_EXCEPTION_COUNTS = {
    "missing_po": 1,
    "duplicate_identity": 1,
    "price_mismatch": 1,
    "quantity_mismatch": 1,
    "corrupted_document": 1,
    "credit_note": 1,
}


def money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def amount(value: Decimal | str | int | float) -> str:
    return f"{money(value):.2f}"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def day(reference: date, offset: int) -> str:
    return (reference + timedelta(days=offset)).isoformat()


def make_vendors(count: int) -> list[dict[str, Any]]:
    vendors = []
    for index, name in enumerate(VENDOR_NAMES[:count], 1):
        vendors.append(
            {
                "id": f"vendor-{index:03d}",
                "legal_name": name,
                "aliases": [
                    name.replace("Company", "Co.").replace("Components", "Parts"),
                    name.upper(),
                ],
                "tax_id": f"SYN-TAX-{index:05d}",
                "email": f"ap@vendor-{index:03d}.example.com",
                "is_synthetic": True,
            }
        )
    return vendors


def make_purchase_orders(
    count: int, vendors: list[dict[str, Any]], reference: date, rng: random.Random
) -> list[dict[str, Any]]:
    orders = []
    for index in range(1, count + 1):
        vendor = vendors[(index - 1) % len(vendors)]
        product_indices = rng.sample(range(len(PRODUCTS)), k=rng.randint(2, 4))
        lines = []
        for line_number, product_index in enumerate(product_indices, 1):
            sku, description, catalog_price = PRODUCTS[product_index]
            price = money(
                Decimal(catalog_price) * Decimal(str(rng.choice(("0.95", "1.00", "1.05"))))
            )
            quantity = rng.randint(65, 95)
            lines.append(
                {
                    "line_number": line_number,
                    "sku": sku,
                    "description": description,
                    "quantity": quantity,
                    "unit_price": amount(price),
                    "total": amount(price * quantity),
                }
            )
        orders.append(
            {
                "id": f"po-{index:04d}",
                "number": f"PO-{reference.year}-{index:04d}",
                "vendor_id": vendor["id"],
                "date": day(reference, -150 + index % 45),
                "currency": "USD" if index % 7 else "EUR",
                "line_items": lines,
                "total": amount(sum(Decimal(line["total"]) for line in lines)),
                "document_path": f"documents/purchase_orders/po-{index:04d}.pdf",
            }
        )
    return orders


def make_receipts(
    count: int, orders: list[dict[str, Any]], reference: date
) -> list[dict[str, Any]]:
    if count < len(orders) or count > len(orders) * 2:
        raise ValueError("Receipt count must be between one and two per PO")
    split_count = count - len(orders)
    receipts = []
    sequence = 0
    for order_index, order in enumerate(orders):
        is_split = order_index < split_count
        fractions = (Decimal("0.60"), Decimal("0.40")) if is_split else (Decimal("1"),)
        for part, fraction in enumerate(fractions, 1):
            sequence += 1
            lines = []
            for po_line in order["line_items"]:
                ordered = po_line["quantity"]
                quantity = (
                    max(1, int(Decimal(ordered) * fraction))
                    if part == 1
                    else ordered - max(1, int(Decimal(ordered) * Decimal("0.60")))
                )
                lines.append({"sku": po_line["sku"], "received_quantity": quantity})
            receipts.append(
                {
                    "id": f"receipt-{sequence:04d}",
                    "po_id": order["id"],
                    "received_at": day(reference, -90 + order_index % 45 + part),
                    "line_items": lines,
                }
            )
    return receipts


def exception_assignments(
    vendor_count: int, invoice_count: int, mode: str, rng: random.Random
) -> dict[int, str]:
    counts = EXCEPTION_COUNTS if mode == "full" else FAST_EXCEPTION_COUNTS
    categories = [category for category, count in counts.items() for _ in range(count)]
    rng.shuffle(categories)
    indices: list[int] = []
    if mode == "full":
        by_vendor: dict[int, list[int]] = defaultdict(list)
        for invoice_index in range(1, invoice_count + 1):
            by_vendor[(invoice_index - 1) % vendor_count].append(invoice_index)
        for vendor_index, candidates in by_vendor.items():
            positions = (2, 5, 8, 11) if vendor_index < 6 else (2, 6, 10)
            indices.extend(candidates[position] for position in positions)
    else:
        indices = [3, 6, 10, 14, 18, 22]
    if len(indices) != len(categories):
        raise AssertionError("Exception allocation count mismatch")
    rng.shuffle(indices)
    return dict(zip(indices, categories, strict=True))


def make_invoices(
    count: int,
    vendors: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    reference: date,
    rng: random.Random,
    exceptions: dict[int, str],
) -> list[dict[str, Any]]:
    orders_by_vendor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in orders:
        orders_by_vendor[order["vendor_id"]].append(order)
    prior_by_vendor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invoices = []
    for index in range(1, count + 1):
        vendor = vendors[(index - 1) % len(vendors)]
        vendor_history = prior_by_vendor[vendor["id"]]
        po_choices = orders_by_vendor[vendor["id"]]
        order = po_choices[(len(vendor_history) // 2) % len(po_choices)]
        exception = exceptions.get(index)
        high_amount_target = exception is None and index % 8 == 0
        if high_amount_target:
            usd_orders = sorted(
                (candidate for candidate in po_choices if candidate["currency"] == "USD"),
                key=lambda candidate: Decimal(candidate["total"]),
                reverse=True,
            )
            order = usd_orders[(len(vendor_history) // 8) % len(usd_orders)]
        layout_group = (
            (0, 1, 2) if len(vendors) == 18 and int(vendor["id"][-3:]) <= 6 else (3, 4, 5, 6, 7)
        )
        if len(vendors) < 18:
            layout_group = tuple(range(8))
        layout = LAYOUT_NAMES[layout_group[(len(vendor_history) + index) % len(layout_group)]]
        po_lines = (
            list(order["line_items"])
            if high_amount_target
            else rng.sample(order["line_items"], k=min(len(order["line_items"]), rng.randint(2, 3)))
        )
        high_quantity = 0
        if high_amount_target:
            unit_sum = sum(Decimal(line["unit_price"]) for line in po_lines)
            high_quantity = (
                int(
                    (APPROVAL_THRESHOLD / (unit_sum * (Decimal("1") + TAX_RATE))).to_integral_value(
                        rounding=ROUND_UP
                    )
                )
                + 1
            )
        lines = []
        for line_number, po_line in enumerate(po_lines, 1):
            quantity = high_quantity if high_amount_target else rng.randint(2, 8)
            price = Decimal(po_line["unit_price"])
            if exception == "price_mismatch" and line_number == 1:
                price = money(price * Decimal("1.17"))
            if exception == "quantity_mismatch" and line_number == 1:
                quantity = po_line["quantity"] + 3
            if exception == "credit_note":
                quantity *= -1
            lines.append(
                {
                    "line_number": line_number,
                    "sku": po_line["sku"],
                    "description": po_line["description"],
                    "quantity": quantity,
                    "unit_price": amount(price),
                    "total": amount(price * quantity),
                }
            )
        subtotal = money(sum(Decimal(line["total"]) for line in lines))
        tax = money(subtotal * TAX_RATE)
        if exception == "tax_mismatch":
            tax = money(tax + Decimal("1.13"))
        total = money(subtotal + tax)
        if exception == "inconsistent_total":
            total = money(total + Decimal("0.67"))
        if high_amount_target and (
            total <= APPROVAL_THRESHOLD
            or any(
                line["quantity"] > po_line["quantity"]
                for line, po_line in zip(lines, po_lines, strict=True)
            )
        ):
            raise AssertionError("High-amount fixture must remain valid against its PO")
        document_kind = "credit_note" if exception == "credit_note" else "invoice"
        # Supplier invoice numbers are deliberately reused *across* vendors.
        invoice_number = f"INV-{reference.year}-{(index - 1) // len(vendors) + 1:04d}"
        revision_of = None
        if exception == "duplicate_identity" and vendor_history:
            original = vendor_history[-2] if len(vendor_history) > 1 else vendor_history[-1]
            invoice_number = original["invoice_number"]
            revision_of = original["id"]
        printed_vendor = vendor["legal_name"]
        if exception == "uncertain_vendor":
            printed_vendor = (
                "Harborline"
                if vendor["id"] in ("vendor-001", "vendor-002")
                else vendor["legal_name"].split()[0] + " Supply"
            )
        elif index % 7 == 0:
            printed_vendor = vendor["aliases"][0]
        po_id = None if exception == "missing_po" else order["id"]
        printed_po = f"PO-MISSING-{index:04d}" if po_id is None else order["number"]
        currency = "ZZZ" if exception == "unsupported_currency" else order["currency"]
        invoice = {
            "id": f"inv-{index:04d}",
            "vendor_id": vendor["id"],
            "po_id": po_id,
            "invoice_number": invoice_number,
            "invoice_date": day(reference, -75 + index % 70),
            "due_date": day(reference, -45 + index % 70),
            "currency": currency,
            "subtotal": amount(subtotal),
            "tax": amount(tax),
            "total": amount(total),
            "line_items": lines,
            "layout": layout,
            "document_kind": document_kind,
            "document_path": f"documents/invoices/inv-{index:04d}.pdf",
            "vendor_name": printed_vendor,
            "po_number": printed_po,
            "exception_type": exception,
            "revision_of_invoice_id": revision_of,
            "is_scanned": index % 5 == 0 or exception == "corrupted_document",
        }
        invoices.append(invoice)
        prior_by_vendor[vendor["id"]].append(invoice)
    return invoices


def make_events(
    invoices: list[dict[str, Any]], reference: date, rng: random.Random, mode: str
) -> list[dict[str, Any]]:
    first_events = []
    for index, invoice in enumerate(invoices, 1):
        vendor_number = int(invoice["vendor_id"][-3:])
        channel = "mailbox" if vendor_number <= 6 else ("drive" if index % 2 else "webhook")
        source_event_id = f"{channel}-synthetic-{index:05d}"
        first_events.append(
            {
                "id": f"event-{index:04d}",
                "invoice_id": invoice["id"],
                "kind": "first_delivery",
                "channel": channel,
                "source_event_id": source_event_id,
                "source_file_id": invoice["id"],
                "document_path": invoice["document_path"],
                "received_at": datetime.combine(
                    reference + timedelta(days=-5 + index % 5), datetime.min.time(), tzinfo=UTC
                )
                .replace(hour=index % 12)
                .isoformat(),
                "redelivery_of_event_id": None,
            }
        )
    alt_count, redelivery_count = (110, 50) if mode == "full" else (10, 6)
    alternate_invoices = rng.sample(invoices, alt_count)
    events = list(first_events)
    for invoice in alternate_invoices:
        index = len(events) + 1
        first = first_events[int(invoice["id"][-4:]) - 1]
        channel = "drive" if first["channel"] != "drive" else "mailbox"
        events.append(
            {
                "id": f"event-{index:04d}",
                "invoice_id": invoice["id"],
                "kind": "alternate_source_attempt",
                "channel": channel,
                "source_event_id": f"{channel}-alternate-{index:05d}",
                "source_file_id": f"alternate-{invoice['id']}",
                "document_path": invoice["document_path"],
                "received_at": (
                    datetime.fromisoformat(first["received_at"]) + timedelta(hours=8)
                ).isoformat(),
                "redelivery_of_event_id": None,
            }
        )
    for original in rng.sample(first_events, redelivery_count):
        index = len(events) + 1
        events.append(
            {
                "id": f"event-{index:04d}",
                "invoice_id": original["invoice_id"],
                "kind": "redelivery",
                "channel": original["channel"],
                "source_event_id": original["source_event_id"],
                "source_file_id": original["source_file_id"],
                "document_path": original["document_path"],
                "received_at": (
                    datetime.fromisoformat(original["received_at"]) + timedelta(hours=1)
                ).isoformat(),
                "redelivery_of_event_id": original["id"],
            }
        )
    return events


def make_accounting_history(invoices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normal = [invoice for invoice in invoices if invoice["exception_type"] is None]
    outcomes = ("accepted", "declined", "accepted_then_timeout")
    history = []
    for index, invoice in enumerate(normal[:30], 1):
        outcome = outcomes[(index - 1) % len(outcomes)]
        history.append(
            {
                "operation_key": f"draft:{invoice['vendor_id']}:{invoice['invoice_number']}",
                "invoice_id": invoice["id"],
                "outcome": outcome,
                "draft_bill_id": f"SYN-DRAFT-{index:05d}" if outcome != "declined" else None,
                "external_status": "DRAFT" if outcome != "declined" else None,
                "error_code": "ACCOUNTING_REJECTED" if outcome == "declined" else None,
                "is_synthetic": True,
            }
        )
    return history


def _summary_panel(pdf: canvas.Canvas, invoice: dict[str, Any], x: float, y: float) -> None:
    pdf.setFillColor(colors.HexColor("#eff5f3"))
    pdf.roundRect(x - 8, y - 68, 224, 84, 8, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#132536"))
    for offset, label, value in (
        (0, "Subtotal", invoice["subtotal"]),
        (23, "Tax", invoice["tax"]),
        (46, "Total", invoice["total"]),
    ):
        pdf.setFont("Helvetica-Bold" if label == "Total" else "Helvetica", 10)
        pdf.drawString(x, y - offset, f"{label}: {value}")


def render_invoice_pdf(invoice: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    layout_index = LAYOUT_NAMES.index(invoice["layout"])
    accent = (
        "#17324D",
        "#146C65",
        "#34465E",
        "#9B6138",
        "#315F6D",
        "#284B63",
        "#637A38",
        "#394D77",
    )[layout_index]
    pdf = canvas.Canvas(str(output), pagesize=letter, invariant=1, pageCompression=1)
    pdf.setTitle(
        f"Synthetic {invoice['document_kind'].replace('_', ' ')} {invoice['invoice_number']}"
    )
    pdf.setAuthor("Synthetic demo dataset - InvoiceOps")
    pdf.setSubject("Fictional invoice for local testing only")
    width, height = letter
    if layout_index in (1, 4, 7):
        pdf.setFillColor(colors.HexColor(accent))
        pdf.rect(0, 0, 58, height, fill=1, stroke=0)
    if layout_index in (0, 3, 6):
        pdf.setFillColor(colors.HexColor(accent))
        pdf.rect(0, height - 115, width, 115, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
    else:
        pdf.setFillColor(colors.HexColor(accent))
    left = 88 if layout_index in (1, 4, 7) else 48
    title = (
        "CREDIT NOTE"
        if invoice["document_kind"] == "credit_note"
        else ("TAX INVOICE" if layout_index in (3, 6) else "INVOICE")
    )
    pdf.setFont("Helvetica-Bold", 25 if layout_index != 2 else 21)
    pdf.drawString(left, height - 65, title)
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(width - 48, height - 57, "SYNTHETIC DEMO DATA")
    if layout_index in (0, 3, 6):
        pdf.setFillColor(colors.HexColor("#132536"))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(left, height - 148, invoice["vendor_name"])
    labels = [
        ("Vendor", invoice["vendor_name"]),
        ("Invoice No", invoice["invoice_number"]),
        ("Invoice Date", invoice["invoice_date"]),
        ("Due Date", invoice["due_date"]),
        ("PO No", invoice["po_number"]),
        ("Currency", invoice["currency"]),
    ]
    meta_x = left if layout_index in (2, 5) else width - 250
    meta_y = height - (188 if layout_index in (2, 5) else 168)
    for line_number, (label, value) in enumerate(labels):
        pdf.setFont("Helvetica-Bold", 9)
        pdf.setFillColor(colors.HexColor("#132536"))
        pdf.drawString(meta_x, meta_y - line_number * 19, f"{label}: {value}")
    table_top = height - (338 if layout_index in (2, 5) else 312)
    pdf.setFillColor(colors.HexColor(accent))
    pdf.roundRect(left, table_top - 8, width - left - 48, 28, 4, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(
        left + 9, table_top + 1, "ITEM | SKU | DESCRIPTION | QUANTITY | UNIT PRICE | TOTAL"
    )
    pdf.setFillColor(colors.HexColor("#132536"))
    for row, line in enumerate(invoice["line_items"]):
        y = table_top - 40 - row * 47
        pdf.setStrokeColor(colors.HexColor("#d8e0e4"))
        pdf.line(left, y - 15, width - 48, y - 15)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(
            left + 9,
            y,
            f"ITEM | {line['sku']} | {line['description']} | {line['quantity']} | {line['unit_price']} | {line['total']}",
        )
    _summary_panel(pdf, invoice, width - 270, table_top - 67 - len(invoice["line_items"]) * 47)
    pdf.setStrokeColor(colors.HexColor("#cad5dc"))
    pdf.line(left, 96, width - 48, 96)
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#60717e"))
    pdf.drawString(
        left, 77, "Payment is outside this demo. No real bank details or recipient are shown."
    )
    pdf.drawString(left, 60, f"Reference: {invoice['invoice_number']}  |  Page 1 of 1")
    pdf.save()


def render_scanned_invoice(invoice: dict[str, Any], pdf_path: Path, png_path: Path) -> None:
    """Create a real image-only PDF and a matching PNG for OCR exercises."""
    scale = 2
    image = Image.new("RGB", (612 * scale, 792 * scale), "#faf9f4")
    draw = ImageDraw.Draw(image)
    bold = ImageFont.load_default(size=33)
    regular = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=18)
    dark = "#263644"
    accent = "#3d6772"
    title = "CREDIT NOTE" if invoice["document_kind"] == "credit_note" else "INVOICE"
    draw.rectangle((0, 0, 1224, 150), fill="#e2e9e8")
    draw.text((90, 55), title, font=bold, fill=dark)
    draw.text((795, 65), "SYNTHETIC DEMO DATA", font=small, fill=accent)
    draw.text((90, 190), f"Vendor: {invoice['vendor_name']}", font=bold, fill=dark)
    labels = [
        ("Invoice No", invoice["invoice_number"]),
        ("Invoice Date", invoice["invoice_date"]),
        ("Due Date", invoice["due_date"]),
        ("PO No", invoice["po_number"]),
        ("Currency", invoice["currency"]),
    ]
    for row, (label, value) in enumerate(labels):
        draw.text((90, 280 + row * 42), f"{label}:  {value}", font=regular, fill=dark)
    draw.rectangle((90, 540, 1130, 588), fill="#dce7e5")
    draw.text((105, 551), "ITEM", font=regular, fill=dark)
    draw.text((795, 551), "QTY", font=regular, fill=dark)
    draw.text((895, 551), "UNIT", font=regular, fill=dark)
    draw.text((1020, 551), "AMOUNT", font=regular, fill=dark)
    for row, line in enumerate(invoice["line_items"]):
        y = 618 + row * 76
        draw.text((105, y), f"{line['sku']}  {line['description'][:28]}", font=small, fill=dark)
        draw.text((800, y), str(line["quantity"]), font=small, fill=dark)
        draw.text((895, y), line["unit_price"], font=small, fill=dark)
        draw.text((1020, y), line["total"], font=small, fill=dark)
        draw.line((90, y + 43, 1130, y + 43), fill="#cbd5d7", width=2)
    footer_y = 950
    for row, (label, value) in enumerate(
        (("Subtotal", invoice["subtotal"]), ("Tax", invoice["tax"]), ("Total", invoice["total"]))
    ):
        draw.text(
            (800, footer_y + row * 48),
            f"{label}: {invoice['currency']} {value}",
            font=regular,
            fill=dark,
        )
    draw.text(
        (90, 1450),
        "Synthetic supplier document. No real payment details.",
        font=small,
        fill="#72818a",
    )
    if invoice["exception_type"] == "corrupted_document":
        draw.rectangle((70, 155, 1160, 1240), fill="#dddcd4")
        for offset in range(0, 1000, 21):
            draw.line((75, 180 + offset, 1150, 220 + offset), fill="#b8b8b1", width=8)
        draw.text((145, 700), "SCAN DAMAGED - RESUBMISSION REQUIRED", font=bold, fill="#5e6262")
        draw.text((90, 1390), f"Scan reference: {invoice['id']}", font=small, fill="#72818a")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(png_path, format="PNG", optimize=False)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(pdf_path), pagesize=letter, invariant=1, pageCompression=1)
    pdf.setTitle(f"Synthetic scan {invoice['invoice_number']}")
    pdf.setAuthor("Synthetic demo dataset - InvoiceOps")
    pdf.drawInlineImage(image, 0, 0, width=612, height=792)
    pdf.save()


def render_po_pdf(order: dict[str, Any], vendor_name: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=letter, invariant=1, pageCompression=1)
    pdf.setTitle(f"Synthetic purchase order {order['number']}")
    pdf.setAuthor("Synthetic demo dataset - InvoiceOps")
    pdf.setFillColor(colors.HexColor("#17324D"))
    pdf.rect(0, 690, 612, 102, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(48, 739, "PURCHASE ORDER")
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(564, 743, "SYNTHETIC DEMO DATA")
    pdf.setFillColor(colors.HexColor("#1d3344"))
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(48, 650, order["number"])
    pdf.setFont("Helvetica", 10)
    pdf.drawString(48, 624, f"Supplier: {vendor_name}")
    pdf.drawString(48, 605, f"Issue date: {order['date']}")
    pdf.drawString(48, 586, f"Currency: {order['currency']}")
    pdf.setStrokeColor(colors.HexColor("#cad5dc"))
    pdf.line(48, 560, 564, 560)
    pdf.setFont("Helvetica-Bold", 9)
    for x, label in (
        (50, "SKU"),
        (135, "DESCRIPTION"),
        (420, "QTY"),
        (470, "UNIT"),
        (535, "TOTAL"),
    ):
        pdf.drawString(x, 540, label)
    pdf.setFont("Helvetica", 9)
    for index, line in enumerate(order["line_items"]):
        y = 510 - index * 40
        pdf.drawString(50, y, line["sku"])
        pdf.drawString(135, y, line["description"][:39])
        pdf.drawRightString(440, y, str(line["quantity"]))
        pdf.drawRightString(510, y, line["unit_price"])
        pdf.drawRightString(564, y, line["total"])
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(564, 270, f"PO total: {order['currency']} {order['total']}")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(48, 72, "Fictional procurement record for local InvoiceOps testing only.")
    pdf.save()


def make_scenarios(
    invoices: list[dict[str, Any]], events: list[dict[str, Any]], mode: str, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if mode != "full":
        return [], []
    first_event_by_invoice = {
        event["invoice_id"]: event for event in events if event["kind"] == "first_delivery"
    }
    dev = [invoice for invoice in invoices if int(invoice["vendor_id"][-3:]) <= 6]
    holdout = [invoice for invoice in invoices if int(invoice["vendor_id"][-3:]) > 6]
    selected = [("development", invoice) for invoice in rng.sample(dev, 30)]
    selected += [("held_out", invoice) for invoice in rng.sample(holdout, 70)]
    inputs = []
    truth = []
    for index, (split, invoice) in enumerate(selected, 1):
        event = first_event_by_invoice[invoice["id"]]
        case_id = f"scenario-{index:03d}"
        exception = invoice["exception_type"]
        approval_route = (
            []
            if exception
            else (
                ["operator", "manager"]
                if Decimal(invoice["total"]) >= APPROVAL_THRESHOLD
                else ["operator"]
            )
        )
        outcome = "needs_review" if exception else "awaiting_approval"
        inputs.append(
            {
                "case_id": case_id,
                "split": split,
                "event_id": event["id"],
                "document_path": invoice["document_path"],
                "entrypoint": event["channel"],
                "schema_version": SCHEMA_VERSION,
            }
        )
        truth.append(
            {
                "case_id": case_id,
                "split": split,
                "invoice_id": invoice["id"],
                "vendor_id": invoice["vendor_id"],
                "layout": invoice["layout"],
                "is_scanned": invoice["is_scanned"],
                "expected_header": {
                    "vendor_name": invoice["vendor_name"],
                    "invoice_number": invoice["invoice_number"],
                    "invoice_date": invoice["invoice_date"],
                    "due_date": invoice["due_date"],
                    "currency": invoice["currency"],
                    "subtotal": invoice["subtotal"],
                    "tax": invoice["tax"],
                    "total": invoice["total"],
                    "po_number": invoice["po_number"],
                },
                "expected_line_items": invoice["line_items"],
                "expected_outcome": outcome,
                "expected_blocking_finding": exception,
                "expected_approval_roles": approval_route,
                "draft_allowed_after_required_approvals": exception is None,
                "expected_draft_count_after_required_approvals": 0 if exception else 1,
                "source_evidence": {"page": 1, "document_path": invoice["document_path"]},
            }
        )
    return inputs, truth


def generate(output_dir: Path, seed: int, reference: date, mode: str) -> dict[str, Any]:
    if mode not in ("fast", "full"):
        raise ValueError("mode must be fast or full")
    rng = random.Random(seed)
    vendor_count, po_count, receipt_count, invoice_count = (
        (18, 100, 160, 240) if mode == "full" else (8, 12, 18, 24)
    )
    vendors = make_vendors(vendor_count)
    orders = make_purchase_orders(po_count, vendors, reference, rng)
    receipts = make_receipts(receipt_count, orders, reference)
    exceptions = exception_assignments(vendor_count, invoice_count, mode, rng)
    invoices = make_invoices(invoice_count, vendors, orders, reference, rng, exceptions)
    for invoice in invoices:
        pdf_path = output_dir / invoice["document_path"]
        if invoice["is_scanned"]:
            png_path = pdf_path.with_suffix(".png")
            render_scanned_invoice(invoice, pdf_path, png_path)
            invoice["image_path"] = png_path.relative_to(output_dir).as_posix()
        else:
            render_invoice_pdf(invoice, pdf_path)
            invoice["image_path"] = None
        invoice["source_hash"] = sha256_file(pdf_path)
    vendor_names = {vendor["id"]: vendor["legal_name"] for vendor in vendors}
    for order in orders:
        render_po_pdf(order, vendor_names[order["vendor_id"]], output_dir / order["document_path"])
        order["source_hash"] = sha256_file(output_dir / order["document_path"])
    events = make_events(invoices, reference, rng, mode)
    invoice_by_id = {invoice["id"]: invoice for invoice in invoices}
    for event in events:
        event["content_hash"] = invoice_by_id[event["invoice_id"]]["source_hash"]
        canonical = {
            key: event[key]
            for key in ("channel", "source_event_id", "source_file_id", "content_hash")
        }
        event["payload_hash"] = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()
    accounting_history = make_accounting_history(invoices)
    scenario_inputs, scenario_truth = make_scenarios(invoices, events, mode, rng)
    public_dir = output_dir / "public"
    for name, rows in (
        ("vendors", vendors),
        ("purchase_orders", orders),
        ("receipts", receipts),
        ("invoices", invoices),
        ("intake_events", events),
        ("accounting_history", accounting_history),
    ):
        write_json(public_dir / f"{name}.json", rows)
    write_json(
        public_dir / "approval_policy.json",
        {
            "id": "synthetic-policy-v1",
            "currency": "USD",
            "high_amount_threshold": amount(APPROVAL_THRESHOLD),
            "threshold_by_currency": {
                "USD": amount(APPROVAL_THRESHOLD),
                "EUR": amount(APPROVAL_THRESHOLD),
            },
            "normal_roles": ["operator"],
            "high_amount_roles": ["operator", "manager"],
            "expiry_hours": 72,
            "separation_of_duties": True,
        },
    )
    write_jsonl(
        output_dir / "evals" / "scenarios" / "development.jsonl",
        [row for row in scenario_inputs if row["split"] == "development"],
    )
    write_jsonl(
        output_dir / "evals" / "scenarios" / "held_out.jsonl",
        [row for row in scenario_inputs if row["split"] == "held_out"],
    )
    write_jsonl(output_dir / "evaluation_private" / "scenario_truth.jsonl", scenario_truth)
    write_json(
        output_dir / "evaluation_private" / "invoice_truth.json",
        [
            {
                "invoice_id": invoice["id"],
                "header": {
                    key: invoice[key]
                    for key in (
                        "vendor_id",
                        "invoice_number",
                        "invoice_date",
                        "currency",
                        "subtotal",
                        "tax",
                        "total",
                    )
                },
                "line_items": invoice["line_items"],
                "exception": invoice["exception_type"],
            }
            for invoice in invoices
        ],
    )
    write_json(
        output_dir / "evaluation_private" / "DO_NOT_MOUNT.json",
        {
            "purpose": "Offline evaluation labels only. Do not mount into the extractor, n8n, or review portal.",
            "schema_version": SCHEMA_VERSION,
        },
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "dataset_label": "Synthetic demo dataset",
        "seed": seed,
        "reference_date": reference.isoformat(),
        "mode": mode,
        "counts": {
            "vendors": len(vendors),
            "layouts": len({invoice["layout"] for invoice in invoices}),
            "invoices": len(invoices),
            "purchase_orders": len(orders),
            "receipts": len(receipts),
            "intake_events": len(events),
            "exact_redeliveries": sum(event["kind"] == "redelivery" for event in events),
            "alternate_source_attempts": sum(
                event["kind"] == "alternate_source_attempt" for event in events
            ),
            "labeled_exceptions": sum(
                invoice["exception_type"] is not None for invoice in invoices
            ),
            "normal_high_amount_invoices": sum(
                invoice["exception_type"] is None and Decimal(invoice["total"]) > APPROVAL_THRESHOLD
                for invoice in invoices
            ),
            "scanned_invoices": sum(invoice["is_scanned"] for invoice in invoices),
            "development_scenarios": sum(row["split"] == "development" for row in scenario_inputs),
            "held_out_scenarios": sum(row["split"] == "held_out" for row in scenario_inputs),
        },
        "exception_distribution": dict(
            sorted(
                Counter(
                    invoice["exception_type"] for invoice in invoices if invoice["exception_type"]
                ).items()
            )
        ),
        "layout_distribution": dict(
            sorted(Counter(invoice["layout"] for invoice in invoices).items())
        ),
        "document_hash_manifest": {invoice["id"]: invoice["source_hash"] for invoice in invoices},
    }
    write_json(output_dir / "manifest.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("generated/invoiceops_full"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        default=date.fromisoformat(DEFAULT_REFERENCE_DATE),
    )
    parser.add_argument("--mode", choices=("fast", "full"), default="full")
    args = parser.parse_args()
    result = generate(args.output_dir, args.seed, args.reference_date, args.mode)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "document_hash_manifest"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
