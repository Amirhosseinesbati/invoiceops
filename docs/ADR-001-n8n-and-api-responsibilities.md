# ADR 001: n8n coordinates payable work; API owns durable business state

Status: Accepted for the current pilot. Date: 2026-09-28.

## Context

Invoice intake crosses file sources, extraction, human review, and an accounting side effect. A visual workflow is useful for triggers and routing, while authorization and invoice state require transactions and repeatable checks. A stalled or replayed n8n execution must not become the sole record of an invoice decision.

## Decision

n8n 2.40.7 owns intake webhooks, unpublished connected source triggers, branches, connector calls, and recovery/digest schedules. FastAPI owns workspace-scoped records, validation rules, approval decisions, job leasing, transactional posting claims, and archive metadata. The extraction worker runs a narrow LangGraph pipeline and returns a typed document result; it does not approve or post bills. PostgreSQL business tables are the source of truth, in a database separate from n8n's own state.

## Consequences

Webhook callbacks can be treated as wake-up signals because the API rechecks state. An operator can inspect durable approvals and operation keys after an n8n restart. This design needs explicit API contracts and recovery schedules; it cannot infer success from a green n8n node alone. A claimed operation older than four minutes enters reconciliation before a retry. The connected IMAP trigger's pre-downstream UID watermark still needs a mailbox replay procedure and customer-specific testing before use.
