# Dependencies and reproducibility

## Locked build inputs

| Component | Source in this repository | Current selection |
| --- | --- | --- |
| API runtime | `Dockerfile.api` | Python `3.12.13-slim-bookworm`; `uv` image `0.11.28`; Tesseract OCR installed in image. |
| Python packages | `pyproject.toml`, `uv.lock` | FastAPI, SQLAlchemy, Alembic, psycopg, Pydantic Settings, httpx, LangChain, LangGraph, PostgreSQL checkpointer, PyMuPDF, Pillow, pypdf, ReportLab, pwdlib. The lockfile fixes transitive versions for `uv sync --frozen`. |
| Workflow engine | `compose.yaml`, `workflows/manifest.json` | Self-hosted n8n `2.40.7`; built-in workflow nodes; separate PostgreSQL database. |
| Database | `compose.yaml` | PostgreSQL `17.6-bookworm`; business and n8n databases in the same server. |
| Web build | `apps/web/Dockerfile`, `package.json`, `pnpm-lock.yaml` | Node `24.18.0-alpine`, pnpm `11.19.0`, React `19.3.0`, Vite `8.3.0`, TypeScript `5.9.3`, TanStack Query `5.103.2`, Tailwind `4.3.3`. |
| Web serving | `apps/web/Dockerfile`, `nginx.conf` | nginx `1.29.1-alpine`, proxying `/api` to FastAPI. |

The Compose and Dockerfile image tags are versioned but not digest pinned. For reproducible customer builds, capture image digests and a software bill of materials during release packaging. The Python and pnpm lockfiles should be updated deliberately, with migrations, static workflow validation, and runtime acceptance rerun after upgrades.

## Optional external services

- `MODEL_ID` and `OPENAI_API_KEY` enable the connected LangChain structured extractor. DEMO uses a narrow visible-text parser and Tesseract OCR without model calls.
- A customer-owned IMAP credential or Google Drive OAuth credential is required before publishing their intake workflows. Those credentials are not included in the repository or DEMO bootstrap.
- Xero requires a customer-owned OAuth connection, tenant ID, contact/account/tax mapping, and test organization. The Xero posting and reconciliation workflows remain unpublished in DEMO. A lookup-and-verify reconciliation path exists in source, but no live Xero request or ambiguous-outcome test has been run against an authorized organization. Connected retry remains disabled pending a safe new idempotency key and operator-reviewed flow.

## Dependency change procedure

1. Review the relevant upstream release notes and security notices.
2. Update lockfiles or image tags together with the source change; preserve `uv sync --frozen` and `pnpm install --frozen-lockfile` behavior.
3. Regenerate the n8n JSON pack when its generator changes and run its static reference check.
4. Apply database migrations on a disposable copy, then verify extraction, approval, posting, reconciliation, archive, restart, and cross-workspace paths.
5. Record exact versions, image digests, execution IDs, and observed results in a release note. No runtime compatibility claim follows from the manifest version alone.

See [n8n's Server CLI documentation](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line/) for the import/publish contract and [Xero's changelog](https://developer.xero.com/changelog) for provider API and scope changes.
