# ADR 003: Start with customer-owned installations

Status: Accepted for the current pilot. Date: 2026-09-28.

## Context

Invoices, accounting credentials, and approval decisions are sensitive customer assets. The pilot has workspace scoping and two synthetic workspaces for testing, but it is not a public self-service SaaS. n8n licensing changes with who hosts client workflows and credentials.

## Decision

The initial commercialization path is configuration and support of one customer-controlled installation at a time. Provider credentials and source files remain in the customer environment. A provider-hosted multi-client or embedded offering requires a separate architecture and license review. [n8n's official FAQ](https://support.n8n.io/article/can-i-use-your-license-for-my-use-case) says consulting on client-owned instances is distinct from hosting client workflows/credentials on one's own instance (Enterprise) and embedding n8n for clients (Embed).

## Consequences

Customer onboarding includes ownership of the n8n instance, OAuth/IMAP connections, backup keys, user roles, tax/account mappings, and acceptance tests. The local DEMO passwords, HTTP loopback deployment, and simulated accounting bills are never used as a connected customer configuration. Any future hosted service must revisit licensing, tenant isolation, operational support, retention, and security controls before launch.
