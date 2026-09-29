"""Replay generated intake events through the actual n8n webhook.

Examples:
  python scripts/replay_events.py --list
  python scripts/replay_events.py --event-id event-0001
  python scripts/replay_events.py --event-id event-0038  # exact redelivery

Send a business-identity duplicate only after the original has reached a routed
state, so the duplicate check observes that persisted identity.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def local_token() -> str:
    path = ROOT / ".env"
    if not path.is_file():
        raise RuntimeError("Missing local .env; run scripts/init_env.py first")
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("INTERNAL_TOKEN="):
            token = raw.partition("=")[2].strip().strip('"').strip("'")
            if len(token) >= 24:
                return token
    raise RuntimeError("INTERNAL_TOKEN is missing or too short in local .env")


def local_n8n_url() -> str:
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if raw.startswith("N8N_HOST_PORT="):
            port = int(raw.partition("=")[2].strip())
            if not 1 <= port <= 65535:
                raise ValueError("Invalid N8N_HOST_PORT in local .env")
            return f"http://127.0.0.1:{port}/webhook/invoiceops-intake"
    return "http://127.0.0.1:5678/webhook/invoiceops-intake"


def load_events(dataset_dir: Path) -> list[dict]:
    path = dataset_dir / "public" / "intake_events.json"
    return json.loads(path.read_text(encoding="utf-8"))


def replay(event: dict, dataset_dir: Path, url: str, workspace_id: str, token: str) -> dict:
    root = dataset_dir.resolve()
    document = (dataset_dir / event["document_path"]).resolve()
    if not document.is_relative_to(root):
        raise ValueError(f"Event path escapes dataset: {event['id']}")
    content = document.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    if content_hash != event["content_hash"]:
        raise ValueError(f"Document hash differs from manifest: {event['id']}")
    mime_type = mimetypes.guess_type(document.name)[0] or "application/octet-stream"
    payload = {
        "event_id": event["id"],
        "workspace_id": workspace_id,
        "source_system": "replay",
        "source_id": event["source_event_id"],
        "filename": document.name,
        "mime_type": mime_type,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "received_at": event["received_at"],
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Internal-Token": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read(4096)
            status = response.status
    except HTTPError as exc:
        response_body = exc.read(4096)
        status = exc.code
    except URLError as exc:
        raise RuntimeError(f"n8n webhook unavailable: {exc.reason}") from exc
    try:
        body = json.loads(response_body)
    except json.JSONDecodeError:
        body = {"message": response_body.decode("utf-8", errors="replace")[:300]}
    return {
        "event_id": event["id"],
        "source_id": event["source_event_id"],
        "http_status": status,
        "response": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "generated" / "invoiceops_fast")
    parser.add_argument("--url", default=None)
    parser.add_argument("--workspace-id", default="demo-a")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event-id", action="append")
    group.add_argument("--list", action="store_true")
    args = parser.parse_args()
    events = load_events(args.dataset_dir)
    if args.list:
        for event in events:
            if event["kind"] in {"first_delivery", "redelivery"}:
                print(
                    f"{event['id']}  {event['kind']:<15} {event['invoice_id']}  {event['source_event_id']}"
                )
        return 0
    selected = {event["id"]: event for event in events}
    token = local_token()
    failures = 0
    for event_id in args.event_id:
        if event_id not in selected:
            raise ValueError(f"Unknown event ID: {event_id}")
        result = replay(
            selected[event_id],
            args.dataset_dir,
            args.url or local_n8n_url(),
            args.workspace_id,
            token,
        )
        print(json.dumps(result, ensure_ascii=False))
        failures += int(result["http_status"] >= 400)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Replay failed: {exc}") from exc
