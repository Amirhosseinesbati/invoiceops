"""Contract tests for the synthetic InvoiceOps corpus, independent of app ORM."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from scripts.generate_invoiceops_data import DEFAULT_SEED, generate, money, sha256_file


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


_CORPUS_TEMP: tempfile.TemporaryDirectory[str] | None = None
CORPUS: Path


def setUpModule() -> None:
    global _CORPUS_TEMP, CORPUS
    _CORPUS_TEMP = tempfile.TemporaryDirectory(prefix="invoiceops-full-")
    CORPUS = Path(_CORPUS_TEMP.name)
    generate(CORPUS, DEFAULT_SEED, date(2026, 9, 28), "full")


def tearDownModule() -> None:
    if _CORPUS_TEMP is not None:
        _CORPUS_TEMP.cleanup()


def check_full_cardinality_and_document_integrity(corpus: Path) -> None:
    manifest = read_json(corpus / "manifest.json")
    counts = manifest["counts"]
    expected_counts = {
        "vendors": 18,
        "layouts": 8,
        "invoices": 240,
        "purchase_orders": 100,
        "receipts": 160,
        "intake_events": 400,
        "exact_redeliveries": 50,
        "alternate_source_attempts": 110,
        "labeled_exceptions": 60,
        "scanned_invoices": 53,
        "development_scenarios": 30,
        "held_out_scenarios": 70,
    }
    assert all(counts[key] == value for key, value in expected_counts.items())
    assert counts["normal_high_amount_invoices"] >= 15
    invoices = read_json(corpus / "public/invoices.json")
    orders = read_json(corpus / "public/purchase_orders.json")
    assert all((corpus / row["document_path"]).is_file() for row in invoices + orders)
    assert all(
        sha256_file(corpus / row["document_path"]) == row["source_hash"]
        for row in invoices + orders
    )
    assert len({row["source_hash"] for row in invoices}) == 240


def check_financial_and_relationship_invariants(corpus: Path) -> None:
    vendors = {row["id"] for row in read_json(corpus / "public/vendors.json")}
    orders = {row["id"]: row for row in read_json(corpus / "public/purchase_orders.json")}
    receipts = read_json(corpus / "public/receipts.json")
    invoices = read_json(corpus / "public/invoices.json")
    received_by_po_sku = defaultdict(int)
    for receipt in receipts:
        assert receipt["po_id"] in orders
        for line in receipt["line_items"]:
            received_by_po_sku[(receipt["po_id"], line["sku"])] += line["received_quantity"]
    for order in orders.values():
        assert order["vendor_id"] in vendors
        assert money(sum(Decimal(line["total"]) for line in order["line_items"])) == Decimal(
            order["total"]
        )
        for line in order["line_items"]:
            assert received_by_po_sku[(order["id"], line["sku"])] == line["quantity"]
    for invoice in invoices:
        assert invoice["vendor_id"] in vendors
        assert invoice["po_id"] is None or invoice["po_id"] in orders
        assert date.fromisoformat(invoice["invoice_date"]) < date.fromisoformat(invoice["due_date"])
        assert money(sum(Decimal(line["total"]) for line in invoice["line_items"])) == Decimal(
            invoice["subtotal"]
        )
        for line in invoice["line_items"]:
            assert money(Decimal(line["quantity"]) * Decimal(line["unit_price"])) == Decimal(
                line["total"]
            )
        if invoice["exception_type"] != "inconsistent_total":
            assert money(Decimal(invoice["subtotal"]) + Decimal(invoice["tax"])) == Decimal(
                invoice["total"]
            )
        if invoice["exception_type"] != "tax_mismatch":
            assert money(Decimal(invoice["subtotal"]) * Decimal("0.075")) == Decimal(invoice["tax"])
        if invoice["exception_type"] is None:
            order = orders[invoice["po_id"]]
            assert invoice["currency"] == order["currency"]
            order_lines = {line["sku"]: line for line in order["line_items"]}
            assert all(
                line["sku"] in order_lines
                and line["quantity"] <= order_lines[line["sku"]]["quantity"]
                and line["unit_price"] == order_lines[line["sku"]]["unit_price"]
                for line in invoice["line_items"]
            )


def check_duplicate_event_and_business_identity_semantics(corpus: Path) -> None:
    invoices = read_json(corpus / "public/invoices.json")
    by_invoice = {row["id"]: row for row in invoices}
    events = read_json(corpus / "public/intake_events.json")
    by_event = {row["id"]: row for row in events}
    assert Counter(row["kind"] for row in events) == {
        "first_delivery": 240,
        "alternate_source_attempt": 110,
        "redelivery": 50,
    }
    for event in events:
        invoice = by_invoice[event["invoice_id"]]
        assert event["content_hash"] == invoice["source_hash"]
        assert datetime.fromisoformat(event["received_at"]).date() >= date.fromisoformat(
            invoice["invoice_date"]
        )
        if event["kind"] == "redelivery":
            original = by_event[event["redelivery_of_event_id"]]
            assert event["source_event_id"] == original["source_event_id"]
            assert event["payload_hash"] == original["payload_hash"]
        if event["kind"] == "alternate_source_attempt":
            assert event["redelivery_of_event_id"] is None
            assert event["source_event_id"] not in {
                row["source_event_id"] for row in events if row["kind"] == "first_delivery"
            }
            assert event["source_file_id"] != invoice["id"]
    identities = defaultdict(list)
    for invoice in invoices:
        identities[(invoice["vendor_id"], invoice["invoice_number"])].append(invoice)
    duplicates = [group for group in identities.values() if len(group) > 1]
    assert len(duplicates) == 7
    assert all(
        any(row["exception_type"] == "duplicate_identity" for row in group) for group in duplicates
    )
    assert len({row["invoice_number"] for row in invoices}) < len(invoices)  # cross-vendor reuse


def check_evaluation_split_is_isolated_and_truth_is_separate(corpus: Path) -> None:
    dev = read_jsonl(corpus / "evals/scenarios/development.jsonl")
    held = read_jsonl(corpus / "evals/scenarios/held_out.jsonl")
    labels = read_jsonl(corpus / "evaluation_private/scenario_truth.jsonl")
    assert len(dev) == 30 and len(held) == 70 and len(labels) == 100
    assert {row["case_id"] for row in dev + held} == {row["case_id"] for row in labels}
    assert all("expected_" not in key for row in dev + held for key in row)
    dev_truth = [row for row in labels if row["split"] == "development"]
    held_truth = [row for row in labels if row["split"] == "held_out"]
    assert {row["vendor_id"] for row in dev_truth}.isdisjoint(
        {row["vendor_id"] for row in held_truth}
    )
    assert {row["layout"] for row in dev_truth}.isdisjoint({row["layout"] for row in held_truth})
    assert {row["source_evidence"]["document_path"] for row in dev_truth}.isdisjoint(
        {row["source_evidence"]["document_path"] for row in held_truth}
    )


def check_native_documents_have_parseable_visible_fields(corpus: Path) -> None:
    invoices = read_json(corpus / "public/invoices.json")
    examples = {}
    for invoice in invoices:
        if not invoice["is_scanned"] and invoice["layout"] not in examples:
            examples[invoice["layout"]] = invoice
    assert len(examples) == 8
    for invoice in examples.values():
        with pdfplumber.open(corpus / invoice["document_path"]) as document:
            assert len(document.pages) == 1
            text = document.pages[0].extract_text()
        assert f"Vendor: {invoice['vendor_name']}" in text
        assert f"Invoice No: {invoice['invoice_number']}" in text
        assert f"Invoice Date: {invoice['invoice_date']}" in text
        assert f"PO No: {invoice['po_number']}" in text
        assert f"Currency: {invoice['currency']}" in text
        assert f"Total: {invoice['total']}" in text
        assert text.count("ITEM | ") == len(invoice["line_items"]) + 1


def check_fixed_seed_repeats_document_hashes(tmp_path: Path) -> None:
    first = generate(tmp_path / "a", DEFAULT_SEED, date(2026, 9, 28), "fast")
    second = generate(tmp_path / "b", DEFAULT_SEED, date(2026, 9, 28), "fast")
    assert first["document_hash_manifest"] == second["document_hash_manifest"]
    assert read_json(tmp_path / "a/public/intake_events.json") == read_json(
        tmp_path / "b/public/intake_events.json"
    )


class SyntheticDataTests(unittest.TestCase):
    def test_full_cardinality_and_document_integrity(self) -> None:
        check_full_cardinality_and_document_integrity(CORPUS)

    def test_financial_and_relationship_invariants(self) -> None:
        check_financial_and_relationship_invariants(CORPUS)

    def test_duplicate_event_and_business_identity_semantics(self) -> None:
        check_duplicate_event_and_business_identity_semantics(CORPUS)

    def test_evaluation_split_is_isolated_and_truth_is_separate(self) -> None:
        check_evaluation_split_is_isolated_and_truth_is_separate(CORPUS)

    def test_native_documents_have_parseable_visible_fields(self) -> None:
        check_native_documents_have_parseable_visible_fields(CORPUS)

    def test_fixed_seed_repeats_document_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="invoiceops-repeat-") as temp:
            check_fixed_seed_repeats_document_hashes(Path(temp))


if __name__ == "__main__":
    unittest.main()
