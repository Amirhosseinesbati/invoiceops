from pathlib import Path

import pytest
from invoiceops.extraction import _page_texts, parse_visible_invoice

ROOT = Path(__file__).resolve().parents[1]


def test_demo_extractor_reads_pdf_content_without_truth_file():
    documents = sorted(
        (ROOT / "generated" / "invoiceops_fast" / "documents" / "invoices").glob("*.pdf")
    )
    if not documents:
        pytest.skip("Generate the fast synthetic dataset first")
    pages, warnings = _page_texts(documents[0])
    extracted = parse_visible_invoice(pages)
    assert extracted.vendor_name
    assert extracted.invoice_number
    assert extracted.po_number
    assert extracted.total > 0
    assert any(item.field == "invoice_number" and item.page >= 1 for item in extracted.evidence)
