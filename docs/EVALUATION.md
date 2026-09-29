# Evaluation protocol and current evidence

**Status as of 2026-09-28:** the DEMO parser was scored on all 100 synthetic scenarios. The held-out supported-document score is 601/603 correct predicted fields and 601/603 expected fields. This exceeds the 95% material-header target for this synthetic fixture. The 100-scenario operational score, live-model quality, and Xero test-organization behavior remain unmeasured.

## Datasets and leakage boundary

The full generator creates 100 cases: 30 development and 70 held out by vendor, layout, and intake event family. Case inputs are under `generated/invoiceops_full/evals/scenarios/`; offline labels are under `generated/invoiceops_full/evaluation_private/`. The extractor, n8n, API, and portal must not mount private labels or use `public/invoices.json` as extraction input. See [DATA_CARD.md](DATA_CARD.md) and [SCENARIOS.md](../evals/SCENARIOS.md).

`evals/runner.py` has two deliberately separate commands. `collect-demo` opens only case input references and document files; it calls the app's PDF/OCR text reader and deterministic visible-field parser. It writes observations before labels are loaded. `score` then reads saved observations and private truth **offline**. Neither command approves invoices or posts bills.

```powershell
python scripts/generate_invoiceops_data.py --mode full --output-dir generated/invoiceops_full --seed 10410 --reference-date 2026-09-28
python evals/runner.py collect-demo --dataset-dir generated/invoiceops_full --split held_out --output generated/evaluation/demo_observations.jsonl
python evals/runner.py score --dataset-dir generated/invoiceops_full --split held_out --observations generated/evaluation/demo_observations.jsonl --results generated/evaluation/held_out_results.json --report generated/evaluation/held_out_report.md
```

The first command is an acceptance-corpus generation step; use it once in a clean directory. The collector requires the app's locked Python dependencies and Tesseract for image-only scans. An unavailable OCR dependency produces a recorded extraction failure; it does not silently substitute fixture truth. The scorer requires only the Python standard library. The measured run used the API/generator container, which includes Tesseract. Windows-host collection without Tesseract produced missing scanned observations and is **not** the result reported below. Machine-readable and Markdown artifacts are under `generated/evaluation/` in this checkout; this generated directory is ignored by Git and should be preserved or regenerated for a release package.

## Header extraction measures

Nine declared header fields are scored: vendor name, invoice number, invoice date, due date, PO number, currency, subtotal, tax, and total. Names are compared after case-folding and whitespace normalization; identifiers and currencies are compared case-insensitively; money is rounded to cents. **Precision** is correct nonempty predictions divided by all nonempty predictions. **Recall/coverage** is correct predictions divided by expected fields. Both numerators and denominators are written to JSON and Markdown. A parser that emits almost nothing cannot claim success because recall and missing observations remain visible.

The held-out release slice excludes intentionally unreadable `corrupted_document` cases and `ZZZ` unsupported-currency cases from the supported-document header target; their failure handling is evaluated operationally. The scorer reports aggregate and per-field figures, plus layout, native versus scanned, and split groups. It records missing observations separately. The target is at least **95% precision** on material supported held-out headers, with recall and human-reviewed samples disclosed. The observed 99.6683% score clears the numeric target on this synthetic slice; manual review and real-document evaluation remain necessary. Synthetic fixture extraction is not a substitute for live-model evaluation.

## Measured synthetic extraction (2026-09-28)

The full corpus was freshly generated with seed `10410` and reference date `2026-09-28`. The DEMO visible-text/OCR collector ran in a container with Tesseract, wrote predictions first, and only then did the offline scorer load private truth. It made no model or accounting-provider calls. The committed [summary report](../evals/results/synthetic_2026-09-28.md) and [machine-readable summary](../evals/results/synthetic_2026-09-28.json) retain exact aggregate counts. The local [development report](../generated/evaluation/development_container_report.md) and [held-out report](../generated/evaluation/held_out_report.md) contain per-case details and are ignored by Git.

| Split or group | Observed scenarios | Supported documents | Correct / predicted nonempty | Correct / expected | Precision and recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 30/30 | 30 | 270/270 | 270/270 | 100.0000% |
| Held out | 70/70 | 67 | 601/603 | 601/603 | 99.6683% |
| Held-out native text | — | — | 486/486 | 486/486 | 100.0000% |
| Held-out scanned | — | — | 115/117 | 115/117 | 98.2906% |

Both wrong held-out fields were `vendor_name` on the scanned `boxed_totals` layout: vendor name 65/67; boxed totals 160/162. The other eight header fields were 67/67 each. Three held-out cases are outside the supported-document target. No observations were missing, but being observed does not mean an unsupported document was extracted correctly. Operational columns in both reports show `0/0` measured; those are pending, not zero accuracy.

## Operational observations

Actual workflow runs must produce a JSONL row with a matching `case_id` and an `operational` object. This is an observation format for the scorer, not a substitute for execution evidence:

```json
{
  "case_id": "scenario-001",
  "extraction": {"vendor_name": "Example Supplier", "invoice_number": "INV-2026-0001"},
  "operational": {
    "status": "awaiting_approval",
    "finding_codes": [],
    "approval_roles": ["operator"],
    "draft_bill_count": 1
  }
}
```

The example is a **shape illustration**, not a measured case. `status`, finding codes, and approval roles should be captured after routing. `draft_bill_count` should be captured only after all required approvals and reconciliation for that case. The scorer compares these fields with private expected outcomes and reports correct/measured counts; absent fields remain unmeasured. Duplicate-identity cases require the preceding vendor/invoice identity in business state. Operational replay must preserve event order or explicitly establish that prerequisite. Save redacted n8n execution IDs, timeline events, and simulator lookup evidence beside the observation file.

At least five **actual triggered** end-to-end scenarios are required for acceptance: clean invoice, exact redelivery, same-identity distinct file, price mismatch requiring resolution, and accepted draft with simulated network timeout/reconciliation. Add credential-error, stale approval, restart, and concurrent retry cases. Manual editor runs or pinned node output do not count. The local n8n replay webhook processed the following actual generated-file events; these observations are separate from the document-only 100-scenario score.

| Triggered event | Observed persisted outcome | Remaining limit |
| --- | --- | --- |
| `event-0001` clean PDF | Version-1 review, operator approval through web UI, `draft_created`, accounting ID `SIM-7240F6658B39`, posting operation accepted on attempt 1, exactly one simulated bill and one archive | Local simulator only. |
| `event-0038` exact redelivery | Returned duplicate of the original invoice ID; bill count remained one | Same source event, not a business-identity duplicate. |
| `event-0002` then `event-0010` | Original reached `awaiting_approval`; distinct file with same vendor and invoice number reached `needs_review` with `DUPLICATE_IDENTITY` | Exception resolution was not exercised. |
| `event-0022` | Reached `needs_review` with `PRICE_MISMATCH` | Exception resolution and subsequent approval/post remain open. |

The accepted-then-timeout reconciliation, credential error, stale approval, restart, concurrent retry, Error Trigger, and cross-workspace checks are still open. Redacted n8n execution IDs and screenshots have not yet been packaged with this report.

## Checks completed so far

| Check | Actual result | Scope |
| --- | --- | --- |
| Synthetic corpus invariant tests | 6 passed in 21.66 s after fresh full generation | Exact counts, relationships, duplicates, split and document integrity. |
| Workflow JSON static check | 18 JSON files passed `bootstrap_workflows.py check` | Reference/shape validation. |
| n8n import and publication | 18 imported; 14 DEMO active, 4 connected inactive | Checked on pinned running image. |
| Actual replay events | `event-0001` completed one draft and archive; `event-0038` redelivery kept one bill; `event-0010` duplicate identity and `event-0022` price mismatch entered review | Timeout and resolution paths remain open. |
| Backend checks | 20 tests passed; Ruff and mypy passed | Local checks after recent fixes. |
| Frontend | Docker build passed; actual operator login, queue and approval displayed persisted state | PDF preview and final responsive/browser inspection in progress. |
| Docker Compose | PostgreSQL/API/n8n/web started and API health passed | Local DEMO; no live provider. |
| Live model and Xero | Pending | Credentials/test organization unavailable. |

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for the latest runtime acceptance checklist. A full synthetic score is only an extraction measurement; it cannot be used as an operational success rate.
