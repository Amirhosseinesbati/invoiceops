"""Deterministic payable rules; no database, HTTP, or model dependencies."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP"}


def money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Invalid amount: {value!r}") from exc


def quantity(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Invalid quantity: {value!r}") from exc


@dataclass(frozen=True)
class RuleFinding:
    code: str
    summary: str
    evidence: dict[str, Any]
    blocking: bool = True


def normalize_name(name: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in name).split())


def resolve_vendor(vendor_name: str, vendors: list[dict[str, Any]]) -> tuple[str | None, bool]:
    target = normalize_name(vendor_name)
    matches = [
        vendor["id"]
        for vendor in vendors
        if target
        in {normalize_name(vendor["name"]), *(normalize_name(x) for x in vendor.get("aliases", []))}
    ]
    unique_matches = set(matches)
    return (
        (next(iter(unique_matches)), False)
        if len(unique_matches) == 1
        else (None, bool(unique_matches))
    )


def validate_document(
    extracted: dict[str, Any],
    po: dict[str, Any] | None,
    receipts: list[dict[str, Any]],
    duplicate_identity: bool,
    tax_rate: Decimal = Decimal("0.075"),
) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    if not extracted.get("invoice_number") or not extracted.get("vendor_name"):
        findings.append(
            RuleFinding("CORRUPTED_DOCUMENT", "Required header fields are unreadable", {})
        )
        return findings
    currency = str(extracted.get("currency", "")).upper()
    if currency not in SUPPORTED_CURRENCIES:
        findings.append(
            RuleFinding(
                "UNSUPPORTED_CURRENCY",
                f"Currency {currency or '?'} is unsupported",
                {"currency": currency},
            )
        )
    if duplicate_identity:
        findings.append(
            RuleFinding("DUPLICATE_IDENTITY", "Vendor and invoice number already exist", {})
        )
    if po is None:
        findings.append(
            RuleFinding(
                "MISSING_PO",
                "No matching purchase order",
                {"po_number": extracted.get("po_number")},
            )
        )
    elif currency != str(po.get("currency", "")).upper():
        findings.append(
            RuleFinding(
                "CURRENCY_MISMATCH",
                "Invoice and PO currencies differ",
                {"invoice": currency, "po": po.get("currency")},
            )
        )

    lines = extracted.get("line_items") or []
    try:
        computed_subtotal = sum(
            (money(quantity(line["quantity"]) * money(line["unit_price"])) for line in lines),
            Decimal("0.00"),
        )
        stated_subtotal = money(extracted.get("subtotal", 0))
        tax = money(extracted.get("tax", 0))
        total = money(extracted.get("total", 0))
        if (
            total < 0
            or stated_subtotal < 0
            or any(quantity(line["quantity"]) < 0 for line in lines)
        ):
            findings.append(
                RuleFinding(
                    "CREDIT_NOTE_UNSUPPORTED",
                    "Credit notes require a separate configured accounting flow",
                    {"total": str(total)},
                )
            )
        if (
            abs(computed_subtotal - stated_subtotal) > CENT
            or abs(stated_subtotal + tax - total) > CENT
        ):
            findings.append(
                RuleFinding(
                    "INCONSISTENT_TOTAL",
                    "Invoice line, subtotal, tax, or total does not reconcile",
                    {
                        "computed_subtotal": str(computed_subtotal),
                        "stated_subtotal": str(stated_subtotal),
                        "tax": str(tax),
                        "total": str(total),
                    },
                )
            )
        if total >= 0 and abs(money(stated_subtotal * tax_rate) - tax) > CENT:
            findings.append(
                RuleFinding(
                    "TAX_MISMATCH",
                    "Invoice tax differs from configured rate",
                    {
                        "expected_tax": str(money(stated_subtotal * tax_rate)),
                        "stated_tax": str(tax),
                        "tax_rate": str(tax_rate),
                    },
                )
            )
    except (KeyError, ValueError) as exc:
        findings.append(
            RuleFinding("CORRUPTED_DOCUMENT", "A line amount is unreadable", {"field": str(exc)})
        )

    if po:
        po_lines = {str(line["sku"]): line for line in po.get("lines", [])}
        received: dict[str, Decimal] = {}
        for receipt in receipts:
            sku = str(receipt["sku"])
            received[sku] = received.get(sku, Decimal(0)) + quantity(receipt["quantity"])
        for line in lines:
            sku = str(line.get("sku", ""))
            matching = po_lines.get(sku)
            if matching is None:
                findings.append(
                    RuleFinding("UNKNOWN_SKU", f"SKU {sku} is absent from the PO", {"sku": sku})
                )
                continue
            try:
                invoice_qty = quantity(line["quantity"])
                po_qty = quantity(matching["quantity"])
                received_qty = received.get(sku, Decimal(0))
                if invoice_qty > po_qty or invoice_qty > received_qty:
                    findings.append(
                        RuleFinding(
                            "QUANTITY_MISMATCH",
                            f"SKU {sku} exceeds ordered or received quantity",
                            {
                                "sku": sku,
                                "invoice": str(invoice_qty),
                                "ordered": str(po_qty),
                                "received": str(received_qty),
                            },
                        )
                    )
                if abs(money(line["unit_price"]) - money(matching["unit_price"])) > CENT:
                    findings.append(
                        RuleFinding(
                            "PRICE_MISMATCH",
                            f"SKU {sku} unit price differs from the PO",
                            {
                                "sku": sku,
                                "invoice": str(line["unit_price"]),
                                "po": str(matching["unit_price"]),
                            },
                        )
                    )
            except (KeyError, ValueError) as exc:
                findings.append(
                    RuleFinding(
                        "CORRUPTED_DOCUMENT", f"SKU {sku} amount is unreadable", {"field": str(exc)}
                    )
                )
    return findings


def required_approval_roles(amount: Decimal, threshold: Decimal) -> tuple[str, ...]:
    return ("operator", "manager") if amount >= threshold else ("operator",)


def may_post(
    *,
    current_version: int,
    approval_version: int,
    required_roles: tuple[str, ...],
    approved_roles: set[str],
    blocking_findings: int,
    duplicate_identity: bool,
    posted: bool,
) -> bool:
    return (
        not posted
        and not duplicate_identity
        and blocking_findings == 0
        and approval_version == current_version
        and set(required_roles).issubset(approved_roles)
    )
