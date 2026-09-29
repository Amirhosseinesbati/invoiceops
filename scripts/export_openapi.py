"""Write the portal's checked-in OpenAPI snapshot from the FastAPI app."""

import json
from pathlib import Path

from invoiceops.main import app

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "apps" / "web" / "src" / "api" / "openapi.json"


def main() -> None:
    TARGET.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET}")


if __name__ == "__main__":
    main()
