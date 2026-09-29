# Commercialization and connected deployment

The current package is a local pilot. A practical initial service is installation, configuration, validation, and support of an InvoiceOps instance controlled by one customer. The customer supplies its mailbox or Drive connection, accounting test organization, approval roles, mapping, retention policy, and hosting environment. Pricing, jurisdictional tax rules, or a broad public multi-tenant service are not encoded in this repository.

## n8n licensing boundary

[n8n's official licensing FAQ](https://support.n8n.io/article/can-i-use-your-license-for-my-use-case) distinguishes three models: consulting on a client's own internal n8n instance, hosting clients' workflows and credentials on the provider's own instance, and embedding n8n in a product exposed to clients. The FAQ says the first can be consulting without a commercial license on the consultant's part (the client may still need a plan for its use case); hosting client workflows and credentials on the provider's instance requires Enterprise; embedding requires an Embed license. Confirm the intended commercial arrangement with n8n before offering hosted or embedded service. This document is an implementation boundary, not legal advice.

The checked-in Compose stack binds n8n to localhost and seeds two workspaces for isolation testing. Those demo workspaces do not turn it into a production multi-tenant offering. [ADR-003](ADR-003-customer-owned-installation.md) records the installation choice.

## Xero connector gate

The separate Xero Draft Post workflow sends an `Invoices` request with `Type='ACCPAY'` and `Status='DRAFT'` and an `Idempotency-Key`. It is not published by the DEMO bootstrap. Before a connected release:

1. Obtain customer authorization to a Xero demo or test organization, configure the tenant and an n8n OAuth credential, and verify the connection in that customer's instance.
2. Validate contact IDs, expense account codes, currency, tax behavior, invoice dates, and required fields against the selected organization. Do not reuse the local simulator's `SIM-CONTACT-*` mappings.
3. Request the granular scope needed for invoices. [Xero's 2026 changelog](https://developer.xero.com/changelog) says `accounting.transactions` is being replaced by granular scopes including `accounting.invoices`; existing broad-scope apps have a migration deadline. Recheck scopes at activation time.
4. Implement and test a Xero-side lookup before retrying any uncertain result. [Xero's idempotent-request guide](https://developer.xero.com/documentation/guides/idempotent-requests/idempotency/) describes a six-minute key window; the durable posting ledger and provider lookup are still required after it expires.
5. Exercise accepted, validation failure, credential error, 429, 5xx, timeout-after-acceptance, and restart cases in the authorized test organization. Publish the Xero workflow and switch Approval Resume only after those results are recorded.

The code does not send a payment or bank transfer. Live-provider writes and cross-system compensation are intentionally limited to draft creation and operator-supervised reconciliation.

## Handover package and support boundaries

A customer handover should include the pinned source and lockfiles, generated workflow JSON and manifest, migration history, per-customer secret inventory, provider mapping, backup/restore test evidence, n8n owner/project ownership, runbook, and measured acceptance results. Keep source invoices and OAuth material in the customer's environment. Treat synthetic accuracy results as demonstration evidence only; measure extraction quality on an authorized, representative customer sample before committing to an SLA.
