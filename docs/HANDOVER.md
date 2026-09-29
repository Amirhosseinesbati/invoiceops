# InvoiceOps handover

Date: 2026-09-28. This is an independent portfolio pilot and an **incomplete runtime acceptance** handover. The local stack, n8n import, real clean invoice through one simulated draft and archive, redelivery, duplicate-identity exception, and price-mismatch exception have been observed. Authenticated PDF page preview and responsive browser views at 1440, 1024, and 390 px were inspected. Timeout reconciliation, saved screenshot set, restore, and connected-provider tests still require acceptance evidence.

## Launch in DEMO mode

Prerequisites: Docker Desktop with a healthy daemon and enough free disk space, Docker Compose, PowerShell 7 or a POSIX shell, and Python 3.12+ with the project's locked dependencies for the workflow bootstrap. From this repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo-up.ps1
```

The first launch creates `.env` through `scripts/init_env.py` if needed, builds the local stack, generates the fast synthetic corpus, and starts PostgreSQL, API/worker, n8n, and portal. The default loopback ports are 5678 (n8n) and 8080 (portal); edit `N8N_HOST_PORT` and `WEB_HOST_PORT` in `.env` if occupied. This checkout used 15678 and 18080 because other projects already used the defaults. Complete n8n's first-run owner setup in its UI, or initialize only the loopback DEMO owner with a random password stored in ignored `.env`:

```powershell
.venv\Scripts\python.exe scripts\setup_local_n8n_owner.py
```

Then import and activate only DEMO workflows:

```powershell
.venv\Scripts\python.exe scripts\bootstrap_workflows.py import --activate-demo
```

For POSIX:

```sh
sh scripts/demo-up.sh
.venv/bin/python scripts/setup_local_n8n_owner.py
.venv/bin/python scripts/bootstrap_workflows.py import --activate-demo
```

The portal and n8n URLs use the ports printed by the startup script. Imports remain inactive until the explicit demo activation command. If an import completed but publication was interrupted, rerun only the idempotent publication step:

```powershell
.venv\Scripts\python.exe scripts\bootstrap_workflows.py publish-demo
```

Use only the generated `.env` values locally; do not commit secrets. If `python` is not from the lockfile environment, run `uv sync --frozen` first and use `uv run --frozen python ...` for bootstrap.

### Demo portal accounts

| Workspace | Role | Email | Password |
| --- | --- | --- | --- |
| Demo A | Operator | `operator@example.com` | `demo-operator` |
| Demo A | Manager | `manager@example.com` | `demo-manager` |
| Demo A | Viewer | `viewer@example.com` | `demo-viewer` |
| Demo B | Operator | `operator-b@example.com` | `demo-operator-b` |

These credentials are synthetic local demo credentials only. Change them before any customer deployment. The n8n first-run owner account is separate and must be created locally by the installer.

## Operator walkthrough after the stack starts

1. Confirm `/health`, portal connector health, n8n health, and seeded workspace isolation.
2. Replay a generated file through the actual n8n webhook. The script checks the document hash and sends real PDF bytes:

   ```powershell
   .venv\Scripts\python.exe scripts\replay_events.py --list
   .venv\Scripts\python.exe scripts\replay_events.py --event-id event-0001
   ```

   Observe the triggered n8n execution, job ID, invoice version, evidence, PO comparison, and operator approval.
3. Replay an exact redelivery and a same-vendor duplicate-identity document. Verify no second local draft is created.
4. Replay a price mismatch. Resolve the exception only after evidence review, obtain a fresh approval for the current version, and verify one `DRAFT` bill.
5. Trigger accepted-then-timeout in the accounting simulator. Inspect the uncertain posting, reconciliation lookup, recovered existing draft ID, archive reference, and digest based on stored status.
6. Restart while a job or approval is pending; verify state and attachments survive. Test a stale callback and another workspace's approval/source-link denial.

The running n8n instance processed `event-0001` through web approval, one simulated draft (`SIM-7240F6658B39`), and one archive. Exact redelivery `event-0038` returned the original invoice ID with bill count still one. After original `event-0002`, distinct-file `event-0010` was routed to `DUPLICATE_IDENTITY`; `event-0022` was routed to `PRICE_MISMATCH`. Price-mismatch **resolution** and accepted-then-timeout reconciliation remain open. Save redacted n8n execution IDs and screenshots for these observations. The optional three-message SMTP/IMAP demonstration is documented in [DEMO_MAIL.md](DEMO_MAIL.md); its live mailbox route is not yet verified.

## Implemented and verified matrix

| Area | Source implemented | Verification as of handover | Remaining action |
| --- | --- | --- | --- |
| FastAPI API, worker, business schema/migration | Yes | PostgreSQL migration/seed, API health, and actual extraction, approval, posting and archive passed before Docker storage failed; 22 backend tests passed | Runtime restart, restore and access-boundary checks. |
| React finance portal | Yes | Docker build, real operator login, queue and approval passed; SKU-based PO/receipt mapping and authenticated PDF preview displayed correctly at 1440/1024/390 px | Save 6–8 screenshot files. |
| n8n workflow pack | 18 exported JSON files and bootstrap source | Static check, clean import, 1 credential, 14 DEMO active / 4 connected inactive; clean draft, redelivery, duplicate identity and mismatch actually triggered | Complete resolution, timeout/reconciliation, credential error, Error Trigger/restart/retry tests. |
| Synthetic data generator | Yes, fixed seed and configurable date | Fresh full corpus generated with exact required counts; six invariant tests passed in 21.66 s | Preserve run manifest and hashes in release evidence. |
| Evaluation runner | Yes | Development 270/270; held out 601/603 supported synthetic headers, 70/70 observations | Human-review samples, operational scoring, and live-document evaluation. |
| Local accounting simulator and reconciliation | Source present | Clean approval posted one DRAFT with accepted attempt 1, one bill and one archive; exact redelivery did not add a bill | Trigger accepted-then-timeout and credential-error scenarios; verify lookup before retry. |
| Docker Compose | Yes | PostgreSQL, API, n8n and web started with healthy API; later Docker storage returned input/output errors and API became unhealthy | Repair storage without affecting unrelated projects, then repeat cold start and backup/restore smoke. |
| Live model / Xero | Adapter and unpublished workflow source present | No credentials or authorized test organization supplied | Configure test account, current scopes, bounded smoke tests, and response/reconciliation semantics. |
| Screenshots and portfolio evidence | Shot list documented; browser QA at 1440/1024/390 px completed | Login, queue, approval, exception and PDF source observed; no saved screenshot set yet | Capture 6–8 real screenshot files. |

A fresh `generated/invoiceops_full` corpus and machine-readable `generated/evaluation/` results are present in this checkout. These directories are ignored by Git; regenerate or package them explicitly when handing the project to another machine. No live messages, payments, or production accounts were used.

At the last runtime check, Docker Desktop returned input/output errors for the API container's filesystem and containerd blobs; C: had about 3.2 GB free. The scoped API restart failed. Do not run a global prune or force-stop other projects as part of this handover. Restore Docker storage health before the remaining triggered scenarios. The signed PDF preview itself was successfully rendered in the portal before the storage error.

## Current source revision

This handover is committed with the implementation on the local `main` branch. Run `git rev-parse HEAD` in this directory for the exact checkout commit and `git status --short` for local changes. The final delivery message records the observed commit ID; a file inside its own commit cannot contain that commit's hash without changing it.

## Customer-specific setup still required

Confirm n8n deployment/licensing terms for the intended installation, choose an authorized mailbox or Drive folder, configure webhook authentication and source allowlists, map vendors/POs/receipts and the customer's accounting chart, connect a Xero test organization with verified scopes and DRAFT semantics, set currency/threshold/retention policies, rotate all demo secrets, back up the PostgreSQL business database and n8n encryption key, run a restore smoke test, and complete a representative real-document evaluation before calling the pilot customer-ready.
