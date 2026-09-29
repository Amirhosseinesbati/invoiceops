from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://invoiceops:invoiceops@localhost:5432/invoiceops"
    checkpoint_url: str = "postgresql://invoiceops:invoiceops@localhost:5432/invoiceops"
    data_dir: Path = Path("data")
    mode: str = "DEMO"
    accounting_provider: Literal["demo", "xero"] = Field(
        default="demo", validation_alias="INVOICEOPS_ACCOUNTING_PROVIDER"
    )
    internal_token: str = "development-only-change-me"
    session_secret: str = "development-only-change-me"
    session_cookie_secure: bool = False
    n8n_approval_webhook_url: str = "http://n8n:5678/webhook/invoiceops-approval"
    n8n_resolution_webhook_url: str = "http://n8n:5678/webhook/invoiceops-resolution"
    n8n_job_complete_webhook_url: str = "http://n8n:5678/webhook/invoiceops-job-complete"
    n8n_replay_webhook_url: str = "http://n8n:5678/webhook/invoiceops-intake"
    model_id: str = ""
    openai_api_key: str = ""
    xero_client_id: str = ""
    max_document_bytes: int = 8_000_000
    approval_ttl_hours: int = 72
    high_amount_threshold: str = "1500.00"
    reference_date: str = "2026-09-28"
    tracing_enabled: bool = False
    enable_worker: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
