# Security and data handling

InvoiceOps is designed for a local, single-customer installation. This document describes controls implemented in code and controls still required before real customer use.

## Trust boundaries

- The browser receives only portal `/api` responses. It does not receive `INTERNAL_TOKEN`, n8n credentials, raw n8n callback URLs, or Xero OAuth material.
- Portal sessions are random 12-hour tokens whose SHA-256 digest is stored in PostgreSQL. The cookie is HTTP-only, SameSite `strict`, and `Secure` only when `SESSION_COOKIE_SECURE=true`. Password hashing uses pwdlib's recommended Argon2 configuration.
- `/internal/*` and `/sim/*` compare the `X-Internal-Token` header with the configured token. n8n stores this as an encrypted Header Auth credential; its workflow JSON contains a credential reference, not the token.
- Portal queries scope records to the signed-in user's workspace. Cross-workspace record access is returned as not found. A separate workspace is seeded to exercise this boundary.
- Invoice approval checks user role, current version, proposal hash, expiry, decision state, and separation of people. The posting claim rechecks approvals, blocking findings, duplicate identity, and accounting mapping under a database lock.
- Source previews use a workspace-bound HMAC URL with a ten-minute expiry. The file handler resolves the path and checks it remains under configured `DATA_DIR`.

## Document and model inputs

The portal and internal intake accept only files with supported MIME type and matching PDF, PNG, or JPEG signature, capped at 8,000,000 bytes. The API stores bytes under a content hash and verifies the source hash before extraction. Text and OCR output are untrusted input. The connected structured-model prompt tells the model to extract evidence rather than obey document instructions, but this prompt alone is not a security boundary; deterministic rules and versioned human review remain mandatory.

The synthetic dataset's private truth files must not be mounted into runtime services. Only vendor, PO, receipt, and policy fixtures are seeded; the invoice generator's structured truth is not an extraction source. See [DATA_CARD.md](DATA_CARD.md).

## Accounting side effects

The DEMO simulator accepts only draft payable bills and checks that each request matches an already claimed operation. It uses the immutable operation key and a unique vendor/invoice identity constraint. The workflow records a timeout as `uncertain` and looks up the key before any retry. A live Xero connection requires its own lookup path and explicit customer authorization. No code path creates a payment.

## Deployment requirements and open issues

| Item | Current local state | Required for customer use |
| --- | --- | --- |
| Transport and cookies | Local HTTP on loopback; `SESSION_COOKIE_SECURE=false` fixture default | TLS reverse proxy, secure cookie, controlled host/origin, and proxy hardening. |
| Demo accounts | Fixed fixture emails and passwords | Remove or rotate fixture accounts; provision customer identities and an administrator process. |
| Brute-force / CSRF | Role and SameSite checks exist; no dedicated rate limiter or CSRF token is visible in current code | Add rate limiting and review CSRF/origin strategy for deployment. |
| Secret storage | `.env` is uncommitted; n8n encrypts the imported Header Auth credential | Use a managed secret source, restricted file permissions, rotation, and n8n backup procedures. |
| Connected providers | Xero/IMAP/Drive workflows unpublished with no customer credentials | Configure least-privilege credentials in the customer instance and test token refresh, scope, mailbox replay, and provider errors. |
| Audit and retention | Business timeline, approvals, operations, errors, and archives persist | Define retention, deletion, backup, access review, and export policy for real invoices. |
| Incident recovery | Completed job and missing callback schedules exist | Add safe recovery for a committed `claimed` operation without a provider result and test restore from backup. |

The n8n UI is bound to loopback in Compose. Treat its owner account and import CLI as privileged; the CLI accesses n8n's database directly. The shared n8n Error Trigger currently lacks reliable invoice correlation for every failure, so monitor API and n8n logs as well as the business exception queue. Do not enable connected workflows based only on a successful JSON import.
