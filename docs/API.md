# API contract

The FastAPI application is defined in [main.py](../apps/api/invoiceops/main.py). The portal is proxied under `/api` by nginx at the loopback `WEB_HOST_PORT` (8080 by default); n8n uses `http://api:8000` inside Compose. `/internal/*` and `/sim/*` require `X-Internal-Token`. Portal routes use an HTTP-only `session_token` cookie after login. All examples below describe the current server contract; `invoice_id`, `job_id`, and operation IDs are opaque strings.

## Portal routes

| Method and path | Request | Result |
| --- | --- | --- |
| `POST /api/login` | `{username,password}` | User, workspace, mode; sets a 12-hour session cookie. |
| `POST /api/logout` | — | Deletes the session and cookie. |
| `GET /api/session` | — | Current user, workspace, mode. |
| `GET /api/invoices?status=&q=` | — | `{items,total}` scoped to the session workspace. |
| `GET /api/invoices/{id}` | — | Invoice summary, versions, evidence, findings, approvals, PO, receipts, timeline, accounting ID, signed source URL. |
| `GET /api/files/{source_id}?exp=&sig=` | Optional `preview_page=1..100` | Scoped source file if the HMAC URL is valid and unexpired; with `preview_page`, returns a bounded PNG rendering of that PDF page (or the first supported image). |
| `GET /api/approvals` | — | Workspace approval items. |
| `POST /api/approvals/{id}/decide` | `{decision:'approve'|'reject',proposal_version,note?}` | Persisted decision and invoice status; sends a server-side n8n callback only after the final required approval. |
| `POST /api/invoices/{id}/retry-posting` | `{note}` | DEMO-only operator retry request after an absent-result reconciliation; wakes n8n with a new fenced attempt. |
| `GET /api/exceptions` | — | Workspace exception items. |
| `POST /api/exceptions/{id}/resolve` | `{resolution:'accept'|'reject'|'request_revision',note}` | Persisted resolution; accepted eligible findings can wake n8n routing. |
| `GET /api/vendors` | — | Vendor summary items. |
| `GET /api/vendors/{id}/history` | — | Vendor and its workspace invoices. |
| `GET /api/connectors/health` | — | Current n8n/database/extraction/accounting connection indicators. |
| `GET /api/digests/latest` | — | Latest stored digest counts for the workspace. |
| `POST /api/replay` | Multipart `file` (PDF/PNG/JPEG, at most 8,000,000 bytes) | `{event_id,status:'submitted'}` after n8n intake webhook accepts the event. |

The portal operator dependency allows `operator`, `manager`, and `admin`; viewers can read workspace data but cannot upload, decide, or resolve. An approval decision additionally requires the exact `required_role` on that approval. A mismatch or cross-workspace ID returns 403/404/409 as appropriate.

## n8n and worker routes

| Method and path | Input | Main output |
| --- | --- | --- |
| `POST /internal/intake` | `{event_id,workspace_id,source_system,source_id,filename,mime_type,content_base64,received_at}`; optional `revision_of` | `{invoice_id,duplicate,source_hash,source_file_id}`. Source system is `replay`, `imap`, or `drive`. |
| `POST /internal/jobs` | `{invoice_id}` | `{job_id,status}`. |
| `GET /internal/jobs/{job_id}` | — | `{job_id,status,progress,failure_reason}` plus extraction result on completion. |
| `GET /internal/jobs/pending-completions` | — | Array of `{job_id,invoice_id}` for completed/review/failed jobs lacking ACK. |
| `POST /internal/jobs/{job_id}/ack` | — | `{status:'acknowledged'}` after route/failure handling. |
| `POST /internal/invoices/{id}/validate` | `{job_id}` | `{invoice_id,status,blocking_findings_count,route,validation_version}`. |
| `GET /internal/invoices/{id}/routing-state` | — | Current route, version, and blocking count. |
| `POST /internal/invoices/{id}/route` | `{route,validation_version}` | Persisted exception or approvals. Route is `exception`, `reviewer`, or `manager_and_reviewer`; stale route returns 409. |
| `POST /internal/invoices/{id}/processing-failed` | `{job_id,reason}` | `{status:'failed'}`. |
| `POST /internal/post/claim` | `{invoice_id}` | `{claimed:false,reason,...}` or a claimed operation with `attempt`, `operation_id`, `operation_key`, invoice identity, currency, and bill payload. |
| `POST /internal/post/result` | `{operation_id,attempt,status,accounting_id?,error?}` | Persisted invoice status. Status is `accepted`, `uncertain`, `declined`, or `credential_error`; a stale attempt returns 409. |
| `GET /internal/reconcile/uncertain` | — | Array of `{operation_id,operation_key,invoice_id}`; includes claims older than four minutes after marking them uncertain. |
| `POST /internal/reconcile/result` | `{operation_id,found,accounting_id?}` | `draft_created` if found with ID; otherwise operation `reconciled_absent` and operator-visible invoice `failed`, enabling reviewed DEMO retry. |
| `GET /internal/reconcile/xero-context/{operation_id}` | — | Connected reconciliation identity/amount context for a candidate Xero lookup. |
| `POST /internal/xero/draft-check` | `{operation_id,attempt,invoice}` | Verifies returned Xero DRAFT identity and amounts before recording a connected result. |
| `GET /internal/recovery/pending-postings` | — | Array of `{invoice_id}` approved invoices with no posting operation. |
| `GET /internal/recovery/pending-routes` | — | Array of routing-state objects including `{invoice_id,validation_version,route}` for validating invoices. |
| `POST /internal/invoices/{id}/archive` | — | `{status:'archived',export_path}`; idempotent for an existing archive. Requires `draft_created` and an accounting ID. |
| `POST /internal/digests/run` | — | Per-workspace stored counts. |
| `POST /internal/workflow-errors` | `{workflow_id,execution_id,message,stage,invoice_id?}` | `{status:'recorded'}`. Without `invoice_id`, the server logs only. |
| `POST /internal/simulator/invoices/{id}/outcome` | `{outcome}` | DEMO-only scenario setting: `accepted`, `timeout`, `declined`, `credential_error`. |

`GET /internal/jobs/{id}` includes `schema_version`, `source_hash`, `extraction_version`, `extraction`, `evidence`, `validation_findings`, and `warnings` when a result exists. The worker result is persisted before its authenticated n8n callback. The callback body contains `{job_id,invoice_id}`.

## Accounting simulator

`POST /sim/accounting/bills` receives `{operation_key,workspace_id,vendor_id,invoice_number,amount,currency,bill_payload}` and requires a matching claimed operation and a draft payable payload (`Type='ACCPAY'`, `Status='DRAFT'`). It returns `{status:'accepted',accounting_id}` on acceptance; a replay with the same operation key returns the same bill. Scenario outcomes can return 401 `credential_error`, 422/409 `declined`, or 504 `timeout` after a durable write. `GET /sim/accounting/bills/by-operation/{operation_key}` returns `{found,accounting_id}` for reconciliation. These endpoints are internal-token protected and DEMO only.

FastAPI publishes the generated OpenAPI schema at `/openapi.json`. The React client has a checked-in generated type snapshot under `apps/web/src/api/`; after an API change, run `python scripts/export_openapi.py` with `PYTHONPATH=apps/api`, then `pnpm generate:api` inside `apps/web`. CI checks both snapshots.
