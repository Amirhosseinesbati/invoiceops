# Scenario source and label boundary

`scripts/generate_invoiceops_data.py` is the source of the 100 reproducible operational evaluation cases. Run it in `full` mode to write:

- `generated/invoiceops_full/evals/scenarios/development.jsonl` (30 input-only cases)
- `generated/invoiceops_full/evals/scenarios/held_out.jsonl` (70 input-only cases)
- `generated/invoiceops_full/evaluation_private/scenario_truth.jsonl` (100 offline labels)

Each input record has `case_id`, `split`, `event_id`, `document_path`, `entrypoint`, and `schema_version`. Each private label has expected header fields, line items, blocking finding or approval roles, expected operational outcome, and a source-page evidence reference. The evaluation runner must load labels only after the workflow finishes and compare its persisted observations with them. No label file may be mounted into the extractor or workflow runtime.

Development and held-out cases have disjoint vendors, layouts, and source event families. The current fixture policy uses a 1,500.00 high-amount threshold with operator plus manager approval at or above the threshold. If a customer policy changes, regenerate or version the expected operational labels; do not silently score with the old policy. Operational duplicate-identity cases require earlier invoices to be present in business state before scoring.

Run the invariant tests with:

```powershell
python -m unittest discover -s tests -p test_synthetic_data.py -v
```

These tests verify data generation and PDF visibility. They do not measure model extraction quality or prove n8n workflow acceptance.
