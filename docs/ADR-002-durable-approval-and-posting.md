# ADR 002: Version-bound approvals and a durable posting claim

Status: Accepted for the current pilot. Date: 2026-09-28.

## Context

An approval can become stale when extracted fields or findings change. Provider writes can succeed even when the response is lost. Retrying a write based solely on an HTTP timeout could create two bills.

## Decision

Each invoice validation creates an `InvoiceVersion` with a proposal hash. Approvals reference that version/hash, role, user, and expiry; manager and reviewer actions require distinct people when both roles apply. Before posting, `/internal/post/claim` rechecks the current version, all required approvals, blocking findings, duplicate identity, and accounting mapping under a database lock. A unique `PostingOperation` records the claim and operation key. The DEMO simulator returns the same bill for a repeated operation key. A timeout records `uncertain`; n8n looks up the operation key before recording an accepted or failed reconciliation result. Archive is idempotent after `draft_created`.

## Consequences

Repeated callbacks cannot create a second local posting operation for the same invoice. The system makes no general exactly-once claim for arbitrary third-party APIs. Xero's [idempotency guide](https://developer.xero.com/documentation/guides/idempotent-requests/idempotency/) states a short key window, so connected mode requires a provider lookup and an operator path for unresolved outcomes. A `claimed` operation with no result enters reconciliation once older than four minutes. An operator can retry the DEMO provider only after a recorded absent lookup; connected Xero retry stays disabled until a safe attempt-specific key and operator-reviewed flow are verified. Live Xero behavior remains a release gate.
