"""Create a local .env with random secrets, leaving an existing one untouched."""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / ".env"
if target.exists():
    print(f"Using existing {target}")
else:
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    secret_names = {"POSTGRES_PASSWORD", "INTERNAL_TOKEN", "SESSION_SECRET", "N8N_ENCRYPTION_KEY"}
    lines = []
    for line in template.splitlines():
        name = line.split("=", 1)[0]
        if name in secret_names:
            line = f"{name}={secrets.token_hex(32)}"
        lines.append(line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created {target} with random local secrets")
