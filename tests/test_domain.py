from decimal import Decimal

from invoiceops.domain import may_post, required_approval_roles, resolve_vendor, validate_document


def base_invoice():
    return {
        "vendor_name": "Harbor Paper Co",
        "invoice_number": "HP-101",
        "po_number": "PO-1",
        "currency": "USD",
        "subtotal": "120.00",
        "tax": "9.00",
        "total": "129.00",
        "line_items": [
            {
                "sku": "PAPER-A4",
                "description": "Paper",
                "quantity": 10,
                "unit_price": "12.00",
                "total": "120.00",
            }
        ],
    }


def base_po():
    return {
        "currency": "USD",
        "lines": [{"sku": "PAPER-A4", "quantity": 10, "unit_price": "12.00"}],
    }


def test_clean_invoice_requires_no_exception():
    assert (
        validate_document(base_invoice(), base_po(), [{"sku": "PAPER-A4", "quantity": 10}], False)
        == []
    )


def test_price_quantity_tax_currency_and_identity_are_independent_findings():
    invoice = base_invoice()
    invoice["currency"] = "JPY"
    invoice["tax"] = "14.00"
    invoice["line_items"][0]["quantity"] = 12
    invoice["line_items"][0]["unit_price"] = "13.00"
    codes = {
        f.code
        for f in validate_document(invoice, base_po(), [{"sku": "PAPER-A4", "quantity": 8}], True)
    }
    assert {
        "UNSUPPORTED_CURRENCY",
        "CURRENCY_MISMATCH",
        "DUPLICATE_IDENTITY",
        "INCONSISTENT_TOTAL",
        "PRICE_MISMATCH",
        "QUANTITY_MISMATCH",
    }.issubset(codes)


def test_vendor_aliases_resolve_without_cross_vendor_number_collision():
    vendors = [
        {"id": "a", "name": "Harbor Paper Company", "aliases": ["Harbor Paper Co"]},
        {"id": "b", "name": "Harbor Packaging", "aliases": []},
    ]
    assert resolve_vendor("HARBOR PAPER CO", vendors) == ("a", False)
    assert resolve_vendor("Harbor", vendors) == (None, False)


def test_high_amount_and_exact_version_block_posting():
    assert required_approval_roles(Decimal("1500.00"), Decimal("1500.00")) == (
        "operator",
        "manager",
    )
    valid = dict(
        current_version=2,
        approval_version=2,
        required_roles=("operator", "manager"),
        approved_roles={"operator", "manager"},
        blocking_findings=0,
        duplicate_identity=False,
        posted=False,
    )
    assert may_post(**valid)
    for changed in (
        {"approval_version": 1},
        {"blocking_findings": 1},
        {"duplicate_identity": True},
        {"posted": True},
        {"approved_roles": {"operator"}},
    ):
        assert not may_post(**{**valid, **changed})


def test_tax_mismatch_and_credit_note_block_normal_draft():
    wrong_tax = base_invoice()
    wrong_tax["tax"] = "10.13"
    wrong_tax["total"] = "130.13"
    assert "TAX_MISMATCH" in {
        finding.code
        for finding in validate_document(
            wrong_tax, base_po(), [{"sku": "PAPER-A4", "quantity": 10}], False
        )
    }
    credit = base_invoice()
    credit["line_items"][0]["quantity"] = -10
    credit["subtotal"] = "-120.00"
    credit["tax"] = "-9.00"
    credit["total"] = "-129.00"
    assert "CREDIT_NOTE_UNSUPPORTED" in {
        finding.code
        for finding in validate_document(
            credit, base_po(), [{"sku": "PAPER-A4", "quantity": 10}], False
        )
    }
