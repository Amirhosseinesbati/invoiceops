# Architecture

## Runtime boundaries

```mermaid
flowchart LR
  U[Operator / manager / viewer] --> W[React portal + nginx]
  W -->|cookie /api| A[FastAPI gateway]
  A -->|server-side authenticated callbacks| N[n8n 2.40.7]
  N -->|Header Auth /internal and /sim| A
  A --> B[(Business PostgreSQL database)]
  N --> ND[(Separate n8n database)]
  A --> F[(Scoped source files and archive exports)]
  A --> J[Leased document worker]
  J --> G[LangGraph extraction]
  G --> B
  G -->|CONNECTED only| M[Configured model API]
  N -->|DEMO draft| S[Local accounting simulator]
  S --> B
  N -. configured connected draft .-> X[Xero demo/test organisation]
  I[Unpublished IMAP trigger] -. connected intake .-> N
  D[Unpublished Drive folder trigger] -. connected intake .-> N
```

`compose.yaml` starts PostgreSQL, the fast corpus generator, the API, n8n, and the web proxy. PostgreSQL contains a business database and a distinct n8n database. The API process starts its leased extraction worker; jobs and LangGraph checkpoints survive process restarts. n8n's generated workflows and stable IDs are in `workflows/`, with the generator and bootstrap under `scripts/`.

## Business flow

1. A server-owned webhook event passes n8n Header Auth and reaches `/internal/intake`. `IntakeEvent` deduplicates the source identity; `SourceFile` deduplicates bytes per workspace.
2. n8n starts `/internal/jobs`. The worker leases a job, verifies the source hash, extracts fields, and commits a typed result. It sends an authenticated completion callback. A schedule lists unacknowledged completed/failed jobs if the callback is lost.
3. n8n calls `/internal/invoices/{id}/validate`; the API creates an immutable `InvoiceVersion`, line items, findings, and a computed route. n8n branches to `/route`, which rechecks version and route before creating exceptions or approvals.
4. A portal decision commits first. A callback asks n8n to claim a posting operation; a schedule recovers lost callbacks. The API checks current version, proposal hash, required roles, expiry, blocking findings, duplicate identity, and accounting mapping under a lock.
5. n8n sends the claimed operation to the simulator in DEMO, records accepted/declined/uncertain status, and calls the idempotent archive endpoint after an accepted result. For an uncertain simulator response, reconciliation queries by immutable operation key before recording a result.

The callback is a wake-up signal, not an authorization grant. Every sensitive transition is rechecked against stored state. The posting ledger has one operation per invoice and a unique operation key. See [ADR-002](ADR-002-durable-approval-and-posting.md).

## Core data model

```mermaid
erDiagram
  WORKSPACE ||--o{ USER : has
  WORKSPACE ||--o{ VENDOR : has
  WORKSPACE ||--o{ INVOICE : owns
  WORKSPACE ||--o{ DIGEST_RUN : has
  USER ||--o{ USER_SESSION : signs_in
  VENDOR ||--o{ PURCHASE_ORDER : supplies
  PURCHASE_ORDER ||--o{ RECEIPT : receives
  SOURCE_FILE ||--o{ INVOICE : sourced_by
  SOURCE_FILE ||--o{ INTAKE_EVENT : delivered_as
  INVOICE ||--o{ INTAKE_EVENT : receives
  INVOICE ||--o{ DOCUMENT_JOB : extracts
  INVOICE ||--o{ INVOICE_VERSION : versions
  INVOICE_VERSION ||--o{ LINE_ITEM : contains
  INVOICE_VERSION ||--o{ FINDING : reports
  INVOICE_VERSION ||--o{ APPROVAL : requires
  INVOICE ||--o| POSTING_OPERATION : claims
  POSTING_OPERATION ||--o| SIMULATED_BILL : creates
  INVOICE ||--o{ BUSINESS_EXCEPTION : raises
  INVOICE ||--o{ TIMELINE_EVENT : records
  INVOICE ||--o| ARCHIVE_RECORD : archives
  VENDOR ||--o| ACCOUNTING_MAPPING : maps_to
  WORKSPACE ||--o| APPROVAL_POLICY : configures

  INVOICE {
    string id PK
    string workspace_id FK
    string status
    int current_version
    string accounting_id
  }
  INVOICE_VERSION {
    string id PK
    string invoice_id FK
    int version
    string proposal_hash
  }
  APPROVAL {
    string id PK
    string invoice_version_id FK
    string required_role
    string status
    datetime expires_at
  }
  POSTING_OPERATION {
    string id PK
    string invoice_id FK
    string operation_key UK
    string status
  }
  SOURCE_FILE {
    string id PK
    string workspace_id FK
    string content_hash
    string path
  }
  DOCUMENT_JOB {
    string id PK
    string invoice_id FK
    string status
    bool completion_notified
  }
```

The diagram focuses on operational relationships; [models.py](../apps/api/invoiceops/models.py) defines exact columns and constraints. In particular, source bytes are unique by `(workspace_id, content_hash)`, intake identities by `(workspace_id, source_id)`, approvals by `(invoice_version_id, required_role)`, and posting by invoice and operation key.

## Failure boundaries

- A completed document job is acknowledged only after its route or failure is persisted. Lost callbacks are recovered from `/internal/jobs/pending-completions`.
- Approval and exception-resolution callbacks are best effort; n8n schedules query `/internal/recovery/pending-postings` and `/internal/recovery/pending-routes`.
- An ambiguous bill response sets `uncertain`; simulator reconciliation queries by operation key. A lookup error leaves it uncertain. A negative lookup becomes an operator-visible failure before any retry.
- The shared n8n Error Trigger logs workflow and execution IDs. It cannot always derive an invoice ID, so some failures are log-only rather than rows in the business exception queue.
- A committed `claimed` posting operation with no recorded provider result enters the uncertain reconciliation list after four minutes; provider lookup precedes any retry. Connected-provider retry still requires its own verified absence, safe new idempotency key, and operator review.
