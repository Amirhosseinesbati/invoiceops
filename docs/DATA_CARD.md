# InvoiceOps synthetic data card

## Purpose and scope

**Synthetic demo dataset.** These records describe a fictional small distributor and fictional suppliers. Names, addresses, identifiers, invoice amounts, purchase orders, receipts, and accounting draft IDs are not customer data or evidence of commercial results. The corpus supports local intake, extraction, PO matching, approval, posting, retry, and reconciliation demonstrations. It does not establish accuracy on real customer documents.

The source is [`scripts/generate_invoiceops_data.py`](../scripts/generate_invoiceops_data.py). It uses a fixed default seed (`10410`) and a configurable reference date (`2026-09-28` by default). It makes no model calls and requires only Python, ReportLab, and Pillow to generate. All monetary calculations use decimal arithmetic and half-up rounding to cents.

## Reproduction

From the repository root, after installing the Python requirements:

```powershell
python scripts/generate_invoiceops_data.py --mode fast --seed 10410 --reference-date 2026-09-28 --output-dir generated/invoiceops_fast
python scripts/generate_invoiceops_data.py --mode full --seed 10410 --reference-date 2026-09-28 --output-dir generated/invoiceops_full
```

The same commands work in a POSIX shell. `--reference-date` accepts `YYYY-MM-DD`. The output directory is caller-owned; use a fresh directory when changing seed or mode. The script writes a manifest with counts and SHA-256 hashes. Large generated outputs belong under `generated/` and are reproducible rather than committed to source control. The `fast` mode produces 24 invoice PDFs, 12 PO PDFs, 18 receipts, 40 intake events, and six planted exceptions for startup and smoke tests. The `full` mode is the acceptance corpus.

## Full corpus

| Entity or property | Count | Notes |
| --- | ---: | --- |
| Vendors | 18 | Fictional legal names, aliases, `.example.com` contacts, synthetic tax IDs. |
| Invoice documents | 240 | One-page PDFs, each with stable ID and SHA-256 hash. |
| Invoice layouts | 8 | `classic_grid`, `sidebar_summary`, `compact_ledger`, `header_band`, `boxed_totals`, `minimal_statement`, `warehouse_slip`, `modern_split`. |
| Image-only invoice scans | 53 | PNG plus PDF wrappers. Six scans are deliberately obscured and require resubmission. |
| Native-text invoice PDFs | 187 | Visible, labeled headers and parseable `ITEM` rows. |
| Purchase orders | 100 | Actual PDF documents with structured fixture records. |
| Receipt records | 160 | One or two receipts per PO; 60 POs have split/partial receipts. |
| Invoice intake events | 400 | 240 first deliveries, 110 alternate-source attempts, 50 exact redeliveries. |
| Labeled invoice exceptions | 60 | See distribution below. |
| Evaluation scenarios | 100 | 30 development and 70 held out. |
| Accounting history examples | 30 | Ten accepted, ten declined, ten accepted-then-timeout simulator cases. |

The generator also deliberately creates clean invoices above the 1,500.00 demo threshold so the operator-plus-manager route has meaningful coverage. The exact count is recorded as `normal_high_amount_invoices` in each generated manifest. USD and EUR use the same numerical threshold in this synthetic fixture; a customer deployment needs its own currency policy.

The 110 alternate-source events use new source event/file IDs and the same invoice document bytes; the 50 redeliveries repeat the original source event ID and payload hash under a new delivery ID. This exercises source deduplication separately from content-hash matching. Seven distinct invoice files intentionally reuse a prior number for the **same** vendor, while ordinary numbering is reused across **different** vendors. Business identity must use vendor plus invoice number, not the number alone.

### Planted exceptions

| Primary label | Count | Expected blocking reason |
| --- | ---: | --- |
| `missing_po` | 6 | Printed PO reference has no matching procurement record. |
| `uncertain_vendor` | 6 | Abbreviated supplier identity needs human resolution. |
| `corrupted_document` | 6 | Image scan is visibly obscured; extraction cannot be trusted. |
| `duplicate_identity` | 7 | Distinct file conflicts on vendor and invoice number. |
| `inconsistent_total` | 7 | Printed total differs from subtotal plus tax. |
| `price_mismatch` | 7 | Invoice unit price differs from PO. |
| `quantity_mismatch` | 7 | Invoiced quantity exceeds ordered/received quantity. |
| `tax_mismatch` | 5 | Printed tax differs from the fixture's 7.5% rule. |
| `unsupported_currency` | 4 | `ZZZ` must not proceed to accounting. |
| `credit_note` | 5 | Negative quantities/totals require a distinct operator path. |

The label is the *primary* planted anomaly. A real validator may return multiple findings; for example, unsupported currency may also differ from its PO currency. Credit notes are intentionally not ordinary positive bills. Normal examples have line totals, subtotal, tax, and grand total consistent under the documented fixture rule. Dates run relative to the reference date; invoice due dates are 30 days after invoice dates, and deliveries are not earlier than the invoice date.

## Files and data boundaries

| Generated path | Intended consumer | Contents |
| --- | --- | --- |
| `manifest.json` | setup and verification | Seed, date, counts, distribution, document hashes. |
| `public/vendors.json` | procurement simulator | Vendor IDs, names, aliases, fake contacts. |
| `public/purchase_orders.json` | procurement simulator | PO IDs, supplier IDs, currency, quantities, prices, PDF paths. |
| `public/receipts.json` | procurement simulator | PO-linked received quantities. |
| `public/invoices.json` | **seed/setup only** | Structured synthetic invoice source truth, document paths, hashes, intended exception type. |
| `public/intake_events.json` | intake replay | Source IDs, channel, delivery kind, document path, content and payload hashes. |
| `public/accounting_history.json` | accounting simulator | Accepted, declined, and accepted-then-timeout behaviors. |
| `public/approval_policy.json` | policy seed | Operator review; amount at or above 1,500.00 uses operator and manager, with 72-hour expiry and separation of duties. |
| `documents/invoices/` | extractor and preview | Native-text or image-only PDFs; matching PNGs for scanned examples. |
| `documents/purchase_orders/` | procurement adapter and preview | Rendered PO PDFs. |
| `evals/scenarios/*.jsonl` | evaluation runner | Input references only, with no expected answer fields. |
| `evaluation_private/*` | **offline evaluation only** | Header/line truth and operational outcome labels. |

The extractor must receive document bytes or a scoped document reference only. It must **never** load `public/invoices.json`, `evaluation_private/`, or fixture exception labels to infer extracted fields. The runtime can use the public PO, receipt, vendor, policy, and accounting simulator files, but the invoice seed file is restricted to setup, diagnostics, and UI fixture preparation. Do not mount `evaluation_private/` into n8n, the API, extractor, or portal containers. Document text and OCR output remain untrusted input. All addresses use reserved `example.com` domains and no real payment details appear in the documents.

## Split and leakage prevention

The 100 evaluation cases are selected from first-delivery invoice events. Development cases use vendors 001-006, layouts 1-3, and mailbox event family. Held-out cases use vendors 007-018, layouts 4-8, and Drive/webhook event families. The vendor, layout, document, and event-family groups do not overlap across the two splits. Scanned and native documents occur in both. The generator writes scenario inputs without expected results to `evals/scenarios/`; the corresponding exact headers, line items, finding, approval route, and page-one source evidence live only in `evaluation_private/scenario_truth.jsonl`.

This split tests generalization to unseen synthetic suppliers and templates, but it is still synthetic. Deterministic rule tests, fixture extraction, OCR, and live-model extraction must be reported separately. The release target of 95% material-header precision applies to held-out **supported** documents and requires actual measured numerators, denominators, layout/native/scanned breakdowns, and manual review of samples. No such model-quality result is claimed by generating this corpus.

## Known limitations

- Invoices and POs are one page; there are no handwriting, multilingual tax rules, real banking data, or genuine supplier logos.
- The five supported finance columns and 7.5% fixture tax rule simplify commercial PO matching. Real tax rules, discounts, freight, and partial invoicing require customer configuration.
- Image-only scans exercise OCR, while six damaged scans have deliberately unrecoverable content. Native-text PDFs are easier than many real supplier files.
- The accounting history is a simulator contract, not proof of live Xero behavior. Live connector acceptance and reconciliation must be tested with an authorized demo/test organization.
- Scenario labels are derived from structured source truth and rendered documents, not from the extractor. They measure synthetic correctness only.
