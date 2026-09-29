"""Run a local SQLite API for UI inspection only; n8n is not exercised."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = "sqlite:///" + (ROOT / "data" / "preview.sqlite3").as_posix()
os.environ["DATA_DIR"] = str(ROOT / "data" / "preview-files")
os.environ["ENABLE_WORKER"] = "false"
os.environ["MODE"] = "DEMO"
sys.path.insert(0, str(ROOT / "apps" / "api"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("invoiceops.main:app", host="127.0.0.1", port=8000, reload=False)
