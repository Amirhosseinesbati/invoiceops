"""List synthetic demo messages in the local GreenMail IMAP inbox."""

from __future__ import annotations

import argparse
import imaplib
import os
from email import policy
from email.parser import BytesHeaderParser, BytesParser
from typing import Any

SCENARIO_ORDER = ("clean", "duplicate_identity", "price_mismatch")


def fetched_bytes(response: list[Any]) -> bytes:
    for part in response:
        if isinstance(part, tuple) and isinstance(part[1], bytes):
            return part[1]
    raise RuntimeError("IMAP returned no message data")


def fetch(mail: imaplib.IMAP4, number: bytes, item: str) -> bytes:
    status, response = mail.fetch(number, f"(BODY.PEEK[{item}])")
    if status != "OK" or not response:
        raise RuntimeError(f"IMAP fetch failed for message {number.decode('ascii')}")
    return fetched_bytes(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3143)
    parser.add_argument("--user", choices=("ap", "ops"), default="ap")
    parser.add_argument("--mailbox", default="INBOX")
    parser.add_argument("--run-id", help="Show one run; otherwise show the latest demo run")
    parser.add_argument("--all", action="store_true", help="Show the most recent messages, including digest mail")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--require-complete", action="store_true", help="Fail unless the three demo scenarios are present once each")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    if args.run_id and args.all:
        parser.error("--run-id and --all cannot be combined")

    password = os.environ.get("INVOICEOPS_DEMO_MAIL_PASSWORD", "demo-mail")
    mail = imaplib.IMAP4(args.host, args.port, timeout=15)
    try:
        mail.login(args.user, password)
        status, _ = mail.select(args.mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"cannot select IMAP mailbox {args.mailbox!r}")
        status, response = mail.search(None, "ALL")
        if status != "OK" or not response:
            raise RuntimeError("IMAP search failed")
        numbers = response[0].split()
        indexed = []
        for number in numbers:
            headers = BytesHeaderParser(policy=policy.default).parsebytes(fetch(mail, number, "HEADER"))
            run_id = str(headers.get("X-InvoiceOps-Demo-Run", ""))
            if args.all or run_id:
                indexed.append((number, run_id, str(headers.get("X-InvoiceOps-Demo-Scenario", ""))))

        if args.all:
            selected = indexed[-args.limit :]
            label = f"Most recent {len(selected)} messages in {args.user}/{args.mailbox}"
        else:
            run_id = args.run_id or (indexed[-1][1] if indexed else "")
            selected = [entry for entry in indexed if entry[1] == run_id] if run_id else []
            label = f"Demo run {run_id or '(none)'} in {args.user}/{args.mailbox}"
        print(label)
        for number, _, scenario in selected:
            message = BytesParser(policy=policy.default).parsebytes(fetch(mail, number, ""))
            attachments = [
                f"{part.get_filename() or '(unnamed)'} ({len(part.get_payload(decode=True) or b'')} bytes)"
                for part in message.iter_attachments()
            ]
            print(f"#{number.decode('ascii')} {scenario or 'other'} | {message.get('Subject', '')}")
            print(f"  From: {message.get('From', '')} | Message-ID: {message.get('Message-ID', '')}")
            print(f"  Attachments: {', '.join(attachments) if attachments else '(none)'}")
        if args.require_complete:
            seen = [scenario for _, _, scenario in selected]
            if sorted(seen) != sorted(SCENARIO_ORDER):
                print("Incomplete demo run: expected one clean, one duplicate_identity, and one price_mismatch email.")
                return 2
        if not selected:
            return 2
        return 0
    finally:
        try:
            mail.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
