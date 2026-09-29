# Operations runbook

This runbook describes the checked-in local DEMO configuration. It is a startup and recovery procedure, not proof that a particular checkout has passed end-to-end acceptance. Use [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for actual observed results.

## Start a local pilot

Prerequisites are Docker Desktop or a compatible Docker daemon with Compose, Python 3.12 for local bootstrap scripts, and free loopback ports. The defaults are `127.0.0.1:8080` (portal) and `127.0.0.1:5678` (n8n). Override them with `WEB_HOST_PORT` and `N8N_HOST_PORT` in `.env`; the startup scripts print the actual URLs. This checkout used 18080 and 15678 because the default ports belonged to other projects.

From the project directory on Windows:

```powershell
.\scripts\demo-up.ps1
```

On a POSIX host:

```sh
./scripts/demo-up.sh
```

The startup script creates `.env` with random `POSTGRES_PASSWORD`, `INTERNAL_TOKEN`, `SESSION_SECRET`, and `N8N_ENCRYPTION_KEY` if none exists, then runs `docker compose up -d --build`. The generator makes the fast synthetic corpus; the API startup applies Alembic migrations and seeds two demo workspaces. `.env` is local and must not be committed. Open the URLs printed by the script.

On the first n8n start, create its owner account in the n8n UI, or use the loopback-only DEMO helper below. It stores a random owner password in ignored `.env` without printing it. The server CLI credential import requires an existing owner. Then run:

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_workflows.py check
.\.venv\Scripts\python.exe scripts\setup_local_n8n_owner.py
.\.venv\Scripts\python.exe scripts\bootstrap_workflows.py import --activate-demo
```

Use `python` instead of the local venv path if Python is already on `PATH`. The import creates an n8n Header Auth credential from `INTERNAL_TOKEN` through a temporary in-container file, imports stable-ID workflows unpublished, publishes the 14 DEMO workflows, and restarts n8n. The four connected-only workflows—Xero posting, Xero reconciliation, IMAP intake, and Google Drive intake—stay unpublished. If import succeeds but publication is interrupted, `python scripts/bootstrap_workflows.py publish-demo` resumes only missing DEMO publications and verifies connected workflows remain inactive. The `--activeState=false` import flag and publish/restart behavior follow [n8n's Server CLI documentation](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line/). This checkout imported and published the pack on pinned n8n 2.40.7 and triggered one replay event through review routing.

## Demo access and smoke journey

The seed script creates these **local fixture accounts** in `demo-a`: `operator@example.com` / `demo-operator`, `manager@example.com` / `demo-manager`, and `viewer@example.com` / `demo-viewer`. `operator-b@example.com` / `demo-operator-b` belongs to isolated `demo-b`. Do not use these passwords with real invoice data or expose the pilot beyond a trusted local environment.

After workflow publication, use `python scripts/replay_events.py --list` and `python scripts/replay_events.py --event-id event-0001` to send an actual generated PDF through the n8n Replay Intake webhook. The script validates the file SHA-256 before transmission and uses the local token and configured n8n host port. Observe the n8n Replay Intake and Job Complete Callback executions, then the portal invoice timeline, version, evidence, findings, and approval inbox. An operator approves a normal invoice. A high-amount invoice additionally needs a different manager. Check for one simulated draft ID and an archive record after posting. For an uncertain outcome, set the DEMO simulator outcome through its internal-only API, wait for Reconcile Drafts, and confirm that the existing operation key resolves to one bill. Record actual execution IDs and screenshots rather than assuming a workflow succeeded because it imported. See [DEMO_MAIL.md](DEMO_MAIL.md) for the optional three-message SMTP/IMAP route.

## Health and diagnosis

| Symptom | First check | Action |
| --- | --- | --- |
| Portal unavailable | `docker compose ps`; `docker compose logs web api` | Confirm API health and nginx proxy. |
| n8n import fails before credentials | n8n owner setup screen and `docker compose logs n8n` | Complete owner setup, then retry bootstrap. |
| Intake returns 503 | n8n published Replay Intake webhook and Header Auth credential | Check token parity between API `.env` and imported n8n credential, then inspect triggered execution. |
| Invoice remains extracting | `document_jobs` status, API worker logs, n8n callback execution | Worker retries leased jobs; pending-completion schedule recovers lost callbacks. |
| Invoice remains approved/validating | Recover Approved Postings / Recover Pending Routes executions | Inspect approval version, mapping, findings, and last workflow error. |
| Invoice remains posting/uncertain | `posting_operations` status and Reconcile Drafts execution | Do not issue another provider write until lookup confirms the outcome. A claim older than four minutes enters reconciliation; inspect provider lookup and operation key before any retry. DEMO operator retry requires a recorded absent result. |
| Archive absent after draft | n8n archive node execution and `/internal/invoices/{id}/archive` response | The endpoint is idempotent and requires `draft_created` plus accounting ID. |

`docker compose logs --tail=200 api n8n` and n8n's triggered execution view are the primary diagnostic sources. The shared Error Trigger can log workflow and execution IDs but may lack invoice correlation. Avoid placing source bytes, session cookies, or credentials in support tickets.

## Recovery, backup, and changes

The API stores business state in PostgreSQL and source/archive files under the mounted `./data` directory. n8n stores its workflow state in its separate PostgreSQL database and uses the persistent `n8n_data` volume plus `N8N_ENCRYPTION_KEY`. Back up these together before migration or import. Keep a protected copy of the encryption key; without it, encrypted n8n credentials may be unreadable. The [n8n Server CLI guide](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line/) says workflow and credential CLI exports alone are not a complete instance backup.

### Backup set and restore smoke test

For one consistent backup set, quiesce intake, approvals, and posting first. Capture both PostgreSQL databases (`invoiceops` business tables and `n8n` internal tables), a protected copy of `./data`, the `n8n_data` volume, the exact `.env`/`N8N_ENCRYPTION_KEY`, and the matching source revision and workflow exports. Record capture time and SHA-256 checksums; keep this set outside the repository with access appropriate for invoice content and credentials. Resume the services only after the files and dumps are complete. A workflow JSON export alone omits approvals, postings, binary files, and credentials.

For a restore smoke test, use a **separate copied project directory and separate Compose project/volumes**, with alternate loopback ports and every connected workflow disabled. Restore the two database dumps, `./data`, and `n8n_data` together, then supply the saved encryption key. Apply no new import over the restored n8n DB. Start PostgreSQL/API/n8n/web and check: API health; n8n owner login and decryptable internal credential; the archived source file opens through a scoped portal link; the restored invoice version, approval, operation key, accounting ID, and archive reference match the backup; an exact source redelivery does not create a second draft. Finally record the result and destroy only the isolated restore environment. This smoke procedure is documented but has **not** yet been executed in this checkout.

Workflow IDs are stable. An import with matching IDs overwrites existing n8n records; export and back up customer changes first. Regenerate JSON from `scripts/generate_workflows.py` after editing its source, run `scripts/bootstrap_workflows.py check`, and import only after reviewing changed branches. CLI publish/import while n8n is running needs a restart for schedules and webhooks to reflect the database state.

The recovery query includes a posting claim older than four minutes even when no provider result was recorded, so its outcome is reconciled before retry. DEMO operator retry is available only after lookup records the bill absent; attempt fencing prevents a stale callback from overwriting the newer attempt. The connected Xero posting and reconciliation workflows remain inactive: configure OAuth, tenant and mapping, then verify draft lookup against an authorized test organization. Connected Xero retry remains disabled until a safe new idempotency key and operator-reviewed flow are implemented and verified.
