# InvoiceOps product

InvoiceOps is a self-hosted accounts-payable intake and approval pilot for a small distributor. It receives a PDF, PNG, or JPEG invoice; extracts fields; compares them with a purchase order and receipts; presents findings to an operator; collects version-bound approvals; and creates a **draft** accounting bill. It has no payment or bank-transfer action.

## What the current implementation does

| Area | Current behavior |
| --- | --- |
| Intake | The portal uploads a file through `/api/replay`; n8n accepts the authenticated event and the API deduplicates source events and file hashes. Unpublished IMAP and Google Drive folder workflows are included for customer-owned connections. |
| Extraction | A leased document job runs a LangGraph ingest → extract → normalize → validate pipeline. DEMO parses visible labels and `ITEM` rows; image and image-only PDF text uses Tesseract OCR. CONNECTED invokes a configured LangChain structured model after text/OCR. |
| Matching | Server rules resolve the vendor and compare invoice identity, PO, receipts, amounts, tax, quantities, prices, and currency. Findings carry a blocking flag and evidence. |
| Review | The React portal lists invoices, evidence, approvals, exceptions, vendor history, timeline, connector health, and status digests. An operator resolves eligible exceptions; reviewer and manager approvals are bound to the current invoice version and proposal hash. |
| Posting | n8n requests a transactional posting claim. DEMO writes an `ACCPAY`/`DRAFT` bill to the local simulator, stores the accounting ID, and archives an export reference. A separate Xero posting sub-workflow is imported unpublished and requires customer configuration. |
| Recovery | A worker callback plus n8n schedules recover completed jobs, missed approval and route callbacks, and uncertain simulator writes. An uncertain write is looked up by operation key before a result is recorded. |

The business database, rather than an n8n execution, is the source of truth for invoices, versions, approvals, findings, operations, and archive records. n8n owns triggers, branching, connector calls, and schedules. The API owns authorization, durable state transitions, extraction jobs, and deterministic matching.

## State and human decisions

The main invoice path is `received → extracting → validating → needs_review or awaiting_approval → approved → posting → draft_created`. `rejected`, `failed`, and `uncertain` remain visible. The archive is a separate record after `draft_created`; it does not erase the invoice. A normal invoice needs an operator approval. A high amount needs an operator and a manager, from different people. Blocking findings send an invoice to the exception queue before approval. The exact route is recomputed server-side when n8n asks to persist it.

DEMO uses two seeded workspaces and local simulated bills. The generated corpus has a fast startup subset and a separate full evaluation corpus; details and leakage boundaries are in [DATA_CARD.md](DATA_CARD.md). DEMO credentials are fixtures and must be replaced for any real installation.

## Current limits and verification status

- The connected Xero, IMAP, and Google Drive workflows remain unpublished. OAuth/IMAP credentials, a Xero demo or test organization, contact/account/tax mapping, and Xero-side reconciliation have not been verified in this checkout.
- The connected document extractor requires `MODEL_ID` and `OPENAI_API_KEY`. Synthetic fixture extraction is not a measured real-world accuracy result.
- The workflow JSON pack has static reference validation. Import into n8n 2.40.7 and triggered end-to-end behavior must be recorded separately in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md); a file existing here is not evidence that its trigger ran.
- A crash after a posting claim and before a provider result can leave a claimed operation that needs an operator-controlled recovery path. The scheduled approved-invoice recovery handles only invoices without an operation. Live-provider retry must never assume the Xero idempotency key alone prevents duplicates.
- Rate-limit-aware bounded backoff, real provider lookup, and production mailbox replay procedures are still connected-installation work.

## Pilot acceptance journey

Use a clean generated invoice, a duplicate source delivery, a PO price mismatch, and a simulated accepted-then-timeout bill. The observable evidence is the persisted invoice/version/finding/approval/operation timeline and one draft bill ID. A complete acceptance run also needs a fresh n8n import, real triggered executions, restart during extraction and approval, workspace isolation checks, and browser screenshots at desktop, tablet, and mobile widths. Those checks must be reported with actual results, not inferred from the source files.
