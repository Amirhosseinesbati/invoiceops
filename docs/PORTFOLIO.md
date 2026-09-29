# InvoiceOps — independent portfolio project

## Case study

**Context.** A small distributor's accounts-payable team receives supplier invoices from more than one source, compares them with purchase orders and receipts, routes mismatches, and creates a draft accounting bill only after approval. The costly failure modes are duplicate intake, approving stale document interpretations, and retrying an accounting write whose result is unknown.

**My role.** I designed and implemented InvoiceOps as an independent portfolio project. It is a self-hostable commercial pilot intended for customer-specific installation and customization; it is not evidence of work for a named client, production use, customer revenue, or real-world extraction accuracy.

**Design.** n8n coordinates intake, routing, approvals, posting, exception handling, reconciliation, and digests. PostgreSQL owns business state and an action ledger. A small FastAPI service runs asynchronous document jobs with a LangGraph extraction path and exposes authenticated review/connector APIs. A React finance inbox presents document evidence, PO comparisons, approvals, exceptions, timeline, vendor history, and connector health. The local mode uses real generated documents and local accounting simulations; connected adapters require separately configured authorized accounts.

**Reliability decisions.** Intake stores source identity and content hash. Validation and approval are versioned; approval references the proposal hash. Posting checks the current version, blocking findings, role approvals, and duplicate identity again before claiming a unique operation. A timeout after simulated acceptance moves the operation to reconciliation rather than issuing an immediate second write. Actual n8n runs verified one local draft and archive, exact-redelivery suppression, and duplicate/mismatch exception routing; timeout reconciliation still needs a triggered acceptance run.

**Data and evidence.** A fresh fixed-seed corpus contains 240 rendered invoice PDFs from 18 fictional vendors and eight layouts, 100 purchase orders, 160 receipts, 400 intake events, and 60 labeled exceptions. Six invariant checks passed after regeneration; 20 backend tests and Ruff/mypy passed. The n8n pack imported into pinned n8n 2.40.7; 14 DEMO workflows are active and four connected-only workflows inactive. Real replay created one simulated draft and archive; exact redelivery kept the bill count at one, while a distinct-file duplicate and price mismatch entered review. On supported held-out synthetic documents, the DEMO text/OCR path matched 601/603 material headers (99.6683% precision and recall; scanned 115/117). This is synthetic extraction evidence, not live-model or customer accuracy. Timeout reconciliation, screenshots, live model, and Xero test-organization checks remain open. No exactly-once external delivery claim is made.

## 60–90 second demo script

1. **0–12 s — Intake.** Open the finance inbox and show the synthetic-data banner. Replay a clean invoice email attachment. Show the source event and document job entering n8n and the queue.
2. **12–28 s — Evidence.** Open the invoice drawer. Point to source page, extracted fields, PO and receipt comparison, and the version tied to the proposed amount.
3. **28–42 s — Exceptions.** Replay a duplicate delivery and a price-mismatch email. Show that the duplicate does not create a second business bill and that the mismatch enters an exception queue.
4. **42–58 s — Decision.** Resolve the mismatch with an operator action, then approve the current version using the required role. Show a stale or wrong-role attempt being refused if the demo environment is ready.
5. **58–75 s — Draft and recovery.** Trigger draft posting. Show one simulated `DRAFT` record. Replay the accepted-then-timeout case and its reconciliation lookup, which returns the existing draft ID.
6. **75–90 s — Close.** Show the persisted timeline, archive reference, and digest counts from stored status. State clearly that the demonstration uses fictional data and local connectors.

The script is a planned walkthrough; it must not be recorded or presented as an executed result until actual triggered runs pass.

## 3–5 minute technical walkthrough

1. **Architecture (0:00–0:40).** Draw the browser → authenticated FastAPI gateway → PostgreSQL boundary, with n8n owning workflow transitions and a separate document-job worker owning extraction. Explain why two orchestrators do not both post a bill.
2. **Intake and extraction (0:40–1:25).** Follow a source event through signature/schema validation, source and content hashes, durable file storage, asynchronous job ID, page text/OCR, typed extraction, evidence, and job completion notification.
3. **Business validation (1:25–2:10).** Show deterministic vendor resolution, PO/receipt comparison, amount and currency rules, distinct blocking findings, and a new immutable invoice version.
4. **Approval and side effect (2:10–3:05).** Show proposal hash, operator/manager role policy, expiry, separated decisions, fresh posting checks, unique operation key, and accounting simulator response.
5. **Failure recovery (3:05–3:45).** Explain accepted-write timeout as an uncertain result. Show lookup-before-retry, restart recovery schedule, exception queue, and stored timeline.
6. **Evidence and limits (3:45–5:00).** Review generated scenario split, precision/recall denominators, actual triggered local draft and exception evidence, the remaining operational acceptance checks, pending connected-provider tests, and deployment requirements.

## Three content angles

1. **Idempotency is a business rule:** illustrate why event ID, file hash, and vendor-plus-invoice identity solve different duplicate cases.
2. **Human approval must approve a version:** show the proposal hash, role separation, expiry, and why a corrected document needs a fresh decision.
3. **Timeouts are not failures:** walk through an accepted accounting write with a lost response and the reconciliation step before retry.

## Screenshot plan and verification state

The login, queue, approval, exception state, PDF preview, and invoice drawer were visually inspected in a browser. The PO/receipt comparison was corrected to match by SKU. The drawer was inspected at 1440, 1024, and 390 px and the mobile queue at 390 px; no document-level horizontal overflow appeared. The browser interface did not provide a screenshot-file export, so the required 6–8 saved images have not yet been captured. These are intended paths for a future local capture. Do not use these paths in a public portfolio until files exist and are checked.

| Planned path | View | State |
| --- | --- | --- |
| `docs/screenshots/01-queue-desktop.png` | Queue and aging, 1440 px | Pending |
| `docs/screenshots/02-evidence-po-drawer.png` | Source and PO comparison, 1440 px | Pending |
| `docs/screenshots/03-approval-inbox.png` | Exact approval amount and version | Pending |
| `docs/screenshots/04-exception-resolution.png` | Price mismatch review/error | Pending |
| `docs/screenshots/05-posting-timeline.png` | Draft ID and reconciliation evidence | Pending |
| `docs/screenshots/06-vendor-health.png` | Vendor history and connector health | Pending |
| `docs/screenshots/07-tablet.png` | 1024 px responsive state | Pending |
| `docs/screenshots/08-mobile.png` | 390 px responsive state | Pending |

## Resume bullet templates using verified facts only

- Built an independent accounts-payable pilot using n8n, FastAPI, PostgreSQL, LangGraph, and React; imported 18 workflows into a local n8n instance and triggered a generated invoice through approval, one simulated draft and archive.
- Generated a fixed-seed synthetic corpus with 240 invoice documents, 100 purchase orders, 160 receipts, and 400 intake events; six corpus invariant tests passed after fresh generation.
- Measured 601/603 correct material header fields (99.6683% precision and recall) on 67 supported held-out **synthetic** documents using the local visible-text/OCR parser. Do not describe this as real-document or live-model accuracy.

Add extraction precision, end-to-end success rate, latency, or commercial impact to these bullets only after those values have been measured and recorded with their denominators.
