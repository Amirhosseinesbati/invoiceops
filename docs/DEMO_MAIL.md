# Local invoice email demo

The optional `demo-mail` Compose profile runs [GreenMail](https://greenmail-mail-test.github.io/greenmail/) as an isolated SMTP/IMAP sandbox. It accepts mail on localhost SMTP `3025` and exposes localhost IMAP `3143`. No external mail provider or paid service is involved. The test accounts are `ap@invoiceops.test` and `ops@invoiceops.test`; both use the synthetic password `demo-mail`. The image is pinned to `greenmail/standalone:2.1.13`. Its mailbox is ephemeral and should not be used as the durable business outbox.

## Prepare n8n

1. Generate the fast dataset and start the normal stack as described in [HANDOVER.md](HANDOVER.md). The scripts below read `generated/invoiceops_fast/public/invoices.json` and attach PDFs from `generated/invoiceops_fast/documents/`. They never read private labels.
2. Set `INVOICEOPS_CONNECTED_WORKSPACE_ID=demo-a` in `.env` **before recreating n8n** for this local demo. Import the workflow pack if needed. In `InvoiceOps | IMAP Intake`, map the existing internal-header credential and create an IMAP credential: host `demo-mail`, port `3143`, login `ap`, password `demo-mail`, mailbox `INBOX`, no TLS on this local Compose network. Activate this IMAP workflow only after the credential and workspace are set. It is intentionally inactive by default.
3. Start only the optional mail service:

   ```powershell
   docker compose --profile demo-mail up -d demo-mail
   ```

The GreenMail image and inbox are separate from the normal stack. The sender script permits only loopback SMTP hosts and always addresses `ap@invoiceops.test`.

## Deliver exactly three invoice emails

Run from the repository root. First send the clean original:

```powershell
.venv\Scripts\python.exe scripts\send_demo_mail.py --stage clean
```

Record the printed run ID. Wait until the clean invoice has passed intake, extraction, and validation in n8n/the portal and its business identity is persisted. The operator then explicitly releases the follow-ups:

```powershell
.venv\Scripts\python.exe scripts\send_demo_mail.py --stage followups --run-id RUN_ID_FROM_FIRST_COMMAND --original-ready
```

The first follow-up is a **business-identity duplicate**: the generated invoice's `revision_of_invoice_id` points to the clean invoice and both have the same `(vendor_id, invoice_number)`, while the PDF hashes and email Message-IDs differ. It is **not** a redelivery of the first source event. The second follow-up is a distinct price-mismatch invoice. The sender validates the public manifest, actual PDF signature, file hash, 8 MiB limit, and this identity relationship before SMTP. It stops if the required fixture is unavailable. The `--original-ready` gate prevents the duplicate from racing the original's validation; the script cannot independently verify n8n's business state.

For a fixture check without SMTP, add `--dry-run` to either command. On the fast dataset, the duplicate PDF is scanned; the API image includes Tesseract for that extraction path. A full dataset may select a native-text duplicate when one exists.

## Inspect the inbox and execution

```powershell
.venv\Scripts\python.exe scripts\show_demo_mail.py --run-id RUN_ID_FROM_FIRST_COMMAND --require-complete
```

This read-only IMAP command shows subject, sender, Message-ID, and PDF attachment for the three messages, and exits nonzero if the run does not contain one of each scenario. `--all --user ops` can inspect simulated digest mail if a workflow is configured to send it to the local `ops` mailbox. The script does not print the mailbox password. In n8n, verify three IMAP trigger executions, the clean review branch, the duplicate-identity exception, and the price-mismatch exception. Resolve the mismatch through the portal, approve an exact version with the appropriate role, and verify one intended draft bill plus the saved execution evidence. Mailbox receipt alone does not establish end-to-end acceptance.

The scripts use only the Python standard library. Override the synthetic password for the clients with `INVOICEOPS_DEMO_MAIL_PASSWORD` only if the GreenMail test-account configuration is changed to match. Never point this setup at a real mailbox or SMTP relay.
