# Implementation status

Date: 2026-09-28. InvoiceOps is an independent, local DEMO pilot. The results below are observations from this checkout, not a customer deployment or a live-provider acceptance claim.

## Implemented

- FastAPI review/API gateway, PostgreSQL business models and Alembic migration, durable document worker, LangGraph extraction path, local procurement/accounting simulators, and scoped source-file access.
- Eighteen exported n8n workflows with a manifest and bootstrap script. Intake, asynchronous job completion, validation routing, approval/resolution continuation, posting, reconciliation, archive recovery, error handling, and digest have separate workflow boundaries. Four connected-only workflows stay unpublished in DEMO.
- React finance portal for queue, source evidence and PO comparison, exact-version approval, exceptions, timeline, vendor history, and connector status.
- Fixed-seed full synthetic corpus and 30-development/70-held-out scenario split with offline private labels and a reproducible extraction scorer.
- Optional local GreenMail SMTP/IMAP profile and a staged three-email demo script.

## Checks observed in this environment

| Check | Observed result | Scope and limit |
| --- | --- | --- |
| Docker Compose and images | PostgreSQL, API, n8n, and web built/started; API health passed | Loopback DEMO stack; no customer connectors. |
| Database migration/seed | Applied against PostgreSQL; seeded 2 workspaces, 4 users, 9 vendors, 13 POs, 19 receipts | Fast demo dataset. |
| n8n import/publication | 18 workflows imported, 1 internal Header Auth credential installed, 14 DEMO workflows published, 4 connected-only workflows inactive | Pinned n8n 2.40.7; publication and DB state checked. |
| Actual clean draft | event-0001 returned HTTP 202 through the n8n replay webhook, completed extraction/validation, reached version-1 approval, and was approved in the web UI; invoice became draft_created | Exactly 1 simulated bill and 1 archive; accounting ID SIM-7240F6658B39; posting operation accepted at attempt 1. |
| Actual redelivery | event-0038 returned duplicate of the same invoice ID | Simulated bill count stayed 1. |
| Actual business duplicate | event-0002 original reached awaiting_approval, then distinct-file event-0010 with the same vendor and invoice number reached needs_review with DUPLICATE_IDENTITY | Different source/content, same business identity. |
| Actual mismatch | event-0022 reached needs_review with PRICE_MISMATCH | Exception branch observed; resolution journey remains open. |
| Full synthetic data | Fresh full generation: 240 invoices, 18 vendors, 8 layouts, 100 POs, 160 receipts, 400 events including 50 redeliveries, and 60 exceptions | Synthetic fixtures only. |
| Synthetic invariant tests | 6 passed in 21.66 s after regeneration | Counts, relationships, fixture consistency and split. |
| n8n pack static check | 18 JSON exports and references passed bootstrap_workflows.py check | Static validation plus the separate runtime import above. |
| Development extraction | 30/30 observations; 270/270 correct supported header fields | DEMO parser with visible PDF text/OCR, run in a container with Tesseract. |
| Held-out extraction | 70/70 observations; 67 supported documents; 601/603 correct predicted and expected header fields (precision/recall 99.6683%) | Synthetic fixture measurement. Native 486/486; scanned 115/117. See [EVALUATION.md](EVALUATION.md). |
| Portal | Docker web build, actual operator login/queue and approval passed; PO/receipt comparison matched by SKU; authenticated PDF page preview rendered in-browser | Screenshots inspected at 1440, 1024, and 390 px with no document-level horizontal overflow. The 6–8 image artifact set is not saved. |
| Backend checks | 22 tests passed in 33.82 s; configured Ruff and typed-domain/evaluation mypy passed; portal lint/type and Docker web build passed | Includes signed PDF preview and credential-error unit scenarios. Local tests and static checks; see CI for repeatable gate. |

The held-out score exceeds the brief's 95% target **for supported synthetic documents with this DEMO parser**. It does not establish live-model or real-supplier accuracy. Operational scoring in the 100-scenario evaluation remains unmeasured because collection there was document-only.

## Acceptance still open

- Complete price mismatch **resolution**, accepted-write timeout/reconciliation, credential error, restart, stale callback, and cross-workspace denial **runtime** checks. Timeout, credential error, stale result, and access behavior have focused local tests, but this does not replace triggered n8n evidence. Save redacted n8n execution IDs and business-state evidence for all triggered scenarios, including those already observed.
- Verify the installed n8n Error Trigger from a real triggered failure, optional GreenMail IMAP route, and restore from a backed-up business DB, n8n DB/volume, and encryption key.
- Capture the required 6–8 real screenshot files; browser views were inspected but the computer-use interface did not provide a file export for screenshots.
- Repeat the migration downgrade/upgrade check on a disposable database; final local lint, type, test and frontend checks passed after source changes.
- Test connected model and Xero only with authorized test credentials and a bounded test organization. They are not verified here. The customer-specific IMAP and Google Drive paths also remain inactive until configured and tested.

After the page-preview and API builds, Docker Desktop's storage returned input/output errors on the API container and containerd blobs. The host C: drive had about 3.2 GB free at the last check. A scoped API restart failed at the container's `hosts` file. Do not infer later runtime results from the healthy state observed before this failure; repair Docker storage and preserve other projects' containers before resuming the remaining integration scenarios.

See [HANDOVER.md](HANDOVER.md), [EVALUATION.md](EVALUATION.md), and [OPERATIONS.md](OPERATIONS.md) for reproduction and evidence boundaries.
