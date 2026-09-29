# InvoiceOps n8n workflow pack

This pack targets self-hosted **n8n 2.40.7** and uses built-in nodes only. The JSON files are generated from `scripts/generate_workflows.py`. Each workflow is inactive in source control. `manifest.json` records stable IDs, import order, and dependencies.

## Local configuration

Set `INVOICEOPS_API_BASE_URL=http://api:8000` in the n8n container and a random `INTERNAL_TOKEN` of at least 24 characters in the uncommitted `.env` file. The bootstrap script imports one `httpHeaderAuth` credential with header name `X-Internal-Token`, using the token supplied at runtime. The credential value is never written to the repository. The n8n instance owner must be initialized before credential import.

Run `python scripts/bootstrap_workflows.py check` to validate the pack. On a new local DEMO instance, complete n8n's owner-account setup at its configured loopback URL, or run `python scripts/setup_local_n8n_owner.py` to store a random owner password only in ignored `.env`. The CLI credential importer needs that owner account. With the Compose stack running, use `python scripts/bootstrap_workflows.py import --activate-demo`. The pinned n8n CLI supports `import:workflow --activeState=false`, which imports workflows unpublished before the script publishes the 14 DEMO workflows. If publication is interrupted, `python scripts/bootstrap_workflows.py publish-demo` resumes missing publications and verifies that all four connected-only workflows remain inactive. Import uses stable workflow and credential IDs; the bootstrap restarts n8n so webhook and schedule registrations take effect. On a customer instance, export and back up existing workflows before import; n8n CLI import overwrites records that already use the same ID.

## Execution contract

| Workflow | Trigger / input | Result |
| --- | --- | --- |
| Replay Intake | `POST /webhook/invoiceops-intake` with Header Auth and JSON file event | Persists intake; returns 202 and starts extraction, or 200 for an exact event redelivery |
| Process Document | sub-workflow `{invoice_id}` | Creates a durable document job |
| Job Complete Callback | `POST /webhook/invoiceops-job-complete` `{job_id,invoice_id}` | Acknowledges promptly and calls Finalize Document |
| Recover Job Callbacks | every minute | Processes completed jobs lacking a finalizer ACK |
| Finalize Document | sub-workflow `{job_id,invoice_id}` | Validates, routes exception/reviewer/manager, and ACKs completed or stale jobs |
| Approval Resume | `POST /webhook/invoiceops-approval` `{invoice_id}` | Claims an approved posting operation and calls the configured provider sub-workflow |
| Resolution Resume | `POST /webhook/invoiceops-resolution` `{invoice_id,validation_version}` | Rechecks routing state and requests versioned approval |
| Post Demo Draft | sub-workflow claimed operation | Creates one local simulated draft or records failure/uncertainty; archives an accepted invoice |
| Reconcile Drafts | every five minutes | Marks claims older than four minutes uncertain, looks up the draft, and archives it when found |
| Reconcile Xero Drafts | unpublished schedule, every five minutes | In connected mode, looks up uncertain Xero operations by invoice number and contact, checks identity and amounts, then records a confirmed result |
| Recover Approved Postings | every two minutes | Finds approved invoices whose decision or operator retry callback was lost, then attempts the atomic posting claim |
| Recover Pending Routes | every two minutes | Rechecks current policy for validating invoices whose resolution callback was lost |
| Recover Pending Archives | every two minutes | Archives accepted drafts whose first idempotent archive call failed |
| Status Digest | each morning at 09:00 server time | Builds a digest from persisted business statuses |
| Shared Error Handler | n8n Error Trigger | Logs a redacted workflow error and execution ID |
| Xero Draft Post | unpublished sub-workflow claimed operation | Connected-mode Xero `ACCPAY`/`DRAFT` request; checks returned identity and totals before accepting |
| IMAP Intake | unpublished Email Trigger | Converts supported PDF, PNG, and JPEG attachments to durable intake events |
| Google Drive Intake | unpublished Drive folder trigger | Downloads new files and converts supported bytes to durable intake events |

All inbound webhooks use the n8n Header Auth credential. The portal and worker send the same token in `X-Internal-Token` from their server-side configuration. Browser clients never receive the token or n8n admin credentials.

The shared n8n Error Trigger supplies workflow and execution IDs, but no reliable invoice ID for every failure. `/internal/workflow-errors` records a per-invoice exception only when `invoice_id` is provided; otherwise it writes a server log entry. Item-level failures that must appear in the exception queue need an invoice-correlated reporting path.

The two connected intake workflows remain unpublished in DEMO. Before publishing IMAP Intake, attach a customer-owned `imap` credential to its trigger and set `INVOICEOPS_CONNECTED_WORKSPACE_ID` in n8n. Before publishing Google Drive Intake, attach the same customer-owned `googleDriveOAuth2Api` credential to its trigger and download nodes and also set `GOOGLE_DRIVE_INVOICE_FOLDER_ID`. Both workflows reuse `/internal/intake` and the Process Document sub-workflow. The IMAP trigger's UID watermark is advanced before downstream intake completes in n8n 2.40.7, so failed downstream processing can require a mailbox replay; configure retention/redelivery procedures and verify them on the customer's mailbox before publishing. Drive's file-created trigger watches only the selected folder, not subfolders.

Recovery list contracts are top-level arrays: `/internal/recovery/pending-postings` and `/internal/recovery/pending-archives` yield `{invoice_id}` items; `/internal/recovery/pending-routes` yields `{invoice_id,validation_version}` items. A successful posting claim includes `invoice_id`, `attempt`, and operation fields. Every `/internal/post/result` request includes that attempt so a late response from an older retry cannot overwrite the current result. `/internal/reconcile/uncertain` includes `invoice_id`, `operation_id`, and `operation_key`; claims older than four minutes enter this list before any retry. When lookup confirms no bill, the operation becomes `reconciled_absent`; only an authenticated operator can request a new attempt through `POST /api/invoices/{invoice_id}/retry-posting` with a note. This action is enabled only for the local DEMO simulator. Connected Xero retry remains disabled until an attempt-specific new Xero idempotency key and operator review flow are implemented. `/internal/invoices/{invoice_id}/archive` is idempotent and follows a persisted accepted result.

The Xero post and reconciliation workflows stay unpublished in DEMO. A connected installation must set `INVOICEOPS_ACCOUNTING_PROVIDER=xero` for both the API and n8n, configure its customer-owned `xeroOAuth2Api` credential and `XERO_TENANT_ID`, validate the mapped contact, expense account and tax behavior against that tenant, and publish both Xero workflows before posting. Approval Resume and recovery select the provider from that variable. The connected lookup searches Xero by invoice number and contact; a single exact draft is checked against the approved version's contact, invoice number, currency, subtotal, tax, and total before the operation is accepted. Ambiguous results and mismatches stay uncertain for investigation. A Xero `Idempotency-Key` is a short-term safeguard; its cache expires after six minutes, so a connected retry needs a new key after a verified absence and is currently blocked. No live Xero request was made in the credential-free local build.

## Runtime verification

`bootstrap_workflows.py check` verifies JSON structure, IDs, connections, sub-workflow targets, credential references, and configured URLs. In this checkout, all 18 workflows imported into pinned n8n 2.40.7 with one internal Header Auth credential; 14 DEMO workflows were published and the four connected-only workflows remained inactive. A real generated-PDF replay (`event-0001`) completed its asynchronous document job, received an operator approval in the portal, created one simulated DRAFT bill and one archive. Exact redelivery (`event-0038`) did not add a bill; a distinct-file duplicate (`event-0010`) and price mismatch (`event-0022`) entered review. Timeout reconciliation, Error Trigger behavior, restart, and retry remain separate runtime acceptance checks. Manual editor runs do not prove Error Trigger behavior. Save redacted execution evidence for subsequent triggered scenarios.

Relevant official references: [n8n sub-workflows](https://docs.n8n.io/build/flow-logic/break-workflows-into-smaller-parts/), [error workflows](https://docs.n8n.io/build/flow-logic/handle-errors-gracefully/), [CLI import and publish](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line/), [Xero invoice types](https://developer.xero.com/documentation/api/accounting/types/), and [Xero idempotent requests](https://developer.xero.com/documentation/guides/idempotent-requests/idempotency/).
