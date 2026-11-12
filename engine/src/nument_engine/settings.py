"""Environment settings for the engine (A.12.7). One object, loaded once per process.

Locally the values come from `engine/.env.<APP_ENV>`; in CI they are plain environment variables, which
always win over the file. Secrets are `SecretStr`, so they never show up in logs or reprs.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENGINE_DIR = Path(__file__).resolve().parents[2]  # .../nument-leads/engine
REPO_DIR = ENGINE_DIR.parent
ENV_FILE_DIR = ENGINE_DIR  # where the local engine/.env.<APP_ENV> files live (tests point it elsewhere)


class Settings(BaseSettings):
    """Every engine setting. Field names map to upper-case environment variables (A.12.7)."""

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "prod"] = "dev"

    # Supabase
    database_url: SecretStr
    supabase_url: str = ""
    supabase_service_role_key: SecretStr | None = None

    # AI
    gemini_api_key: SecretStr | None = None
    gemini_api_key_backup: SecretStr | None = None  # second key, used when the first hits its quota (A.13.4)
    openai_api_key: SecretStr | None = None

    # Google
    google_maps_api_key: SecretStr | None = None
    google_service_account_json: SecretStr | None = None
    google_service_account_file: Path | None = None

    # Sheets
    sheet_master_id: str = ""
    sheet_caller_id: str = ""
    sheet_staging_id: str = ""

    # Behaviour
    associate_name: str = "Aditya"
    user_agent: str = "NumentLeadBot/1.0 (+https://nument.in)"
    alert_email: str | None = None
    alert_email_from: str = "Nument Leads <onboarding@resend.dev>"  # a sender Resend accepts for this account
    resend_api_key: SecretStr | None = None  # optional: weekly report and alerts by email (Step 16.6.3)
    backup_passphrase: SecretStr | None = None

    # Paths (not from env)
    segments_dir: Path = ENGINE_DIR / "segments"
    config_dir: Path = ENGINE_DIR / "config"
    prompts_dir: Path = ENGINE_DIR / "prompts"
    cache_dir: Path = ENGINE_DIR / ".cache"

    @model_validator(mode="after")
    def _safety(self) -> Settings:
        # Dev must never hold live sheet ids: protects the founder's real sheets.
        if self.app_env == "dev" and (self.sheet_master_id or self.sheet_caller_id):
            raise ValueError("APP_ENV=dev must not set SHEET_MASTER_ID or SHEET_CALLER_ID (use SHEET_STAGING_ID)")
        if self.app_env == "prod" and not (self.sheet_master_id and self.sheet_caller_id):
            raise ValueError("APP_ENV=prod needs SHEET_MASTER_ID and SHEET_CALLER_ID")
        return self

    def service_account_info(self) -> dict[str, Any]:
        """Google service account as a dict: JSON text from env (CI) or a file (local)."""
        if self.google_service_account_json:
            info: dict[str, Any] = json.loads(self.google_service_account_json.get_secret_value())
            return info
        if self.google_service_account_file:
            info = json.loads(self.google_service_account_file.expanduser().read_text())
            return info
        raise RuntimeError("Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE")

    def target_sheets(self) -> dict[str, str]:
        """Which sheets this environment writes. Dev writes only the staging sheet."""
        if self.app_env == "prod":
            return {"master": self.sheet_master_id, "caller": self.sheet_caller_id}
        return {"master": self.sheet_staging_id}


def env_file_for(env: str) -> Path:
    """Path of the local env file for an environment, for example `engine/.env.dev`."""
    return ENV_FILE_DIR / f".env.{env}"


@lru_cache
def get_settings() -> Settings:
    """Loads engine/.env.<APP_ENV> locally; in CI the variables already exist in the environment."""
    env_file = env_file_for(os.environ.get("APP_ENV", "dev"))
    return Settings(_env_file=env_file if env_file.is_file() else None)
