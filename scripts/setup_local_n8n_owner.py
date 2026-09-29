"""Initialize the first owner of this loopback-only n8n DEMO instance.

The generated password stays in the ignored local .env file. This script never
prints it and refuses to target anything other than the configured loopback port.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def read_env() -> dict[str, str]:
    if not ENV_PATH.is_file():
        raise RuntimeError("Missing local .env; run scripts/init_env.py first")
    values: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, _, value = raw.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def request_json(url: str, payload: dict[str, str] | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        message = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"n8n returned HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Local n8n is unavailable: {exc.reason}") from exc


def main() -> None:
    values = read_env()
    if values.get("MODE", "DEMO") != "DEMO":
        raise RuntimeError("Owner setup helper runs only in DEMO mode")
    port = int(values.get("N8N_HOST_PORT", "5678"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid N8N_HOST_PORT")
    origin = f"http://127.0.0.1:{port}"
    settings = request_json(origin + "/rest/settings")
    setup_required = settings.get("data", {}).get("userManagement", {}).get("showSetupOnFirstLoad")
    if setup_required is False:
        print("n8n owner is already initialized")
        return
    if setup_required is not True:
        raise RuntimeError("Could not verify n8n first-owner setup state")
    email = values.get("N8N_OWNER_EMAIL", "owner@invoiceops.test")
    password = values.get("N8N_OWNER_PASSWORD")
    additions = []
    if "N8N_OWNER_EMAIL" not in values:
        additions.append(f"N8N_OWNER_EMAIL={email}")
    if not password:
        password = "InvoiceOps-A9!" + secrets.token_urlsafe(24)
        additions.append(f"N8N_OWNER_PASSWORD={password}")
    if additions:
        with ENV_PATH.open("a", encoding="utf-8") as target:
            target.write("\n".join(additions) + "\n")
    request_json(
        origin + "/rest/owner/setup",
        {
            "email": email,
            "firstName": "InvoiceOps",
            "lastName": "Demo",
            "password": password,
        },
    )
    print("n8n owner initialized; local credentials are stored only in .env")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Owner setup failed: {exc}") from exc
