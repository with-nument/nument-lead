"""Environment settings (A.12.7) and their safety rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nument_engine import settings as settings_module
from nument_engine.settings import Settings, get_settings


def test_dev_refuses_live_sheet_ids() -> None:
    with pytest.raises(ValidationError, match="must not set SHEET_MASTER_ID"):
        Settings(app_env="dev", database_url="postgresql://x", sheet_master_id="LIVE")
    with pytest.raises(ValidationError):
        Settings(app_env="dev", database_url="postgresql://x", sheet_caller_id="LIVE")


def test_prod_needs_both_live_sheets() -> None:
    with pytest.raises(ValidationError, match="needs SHEET_MASTER_ID and SHEET_CALLER_ID"):
        Settings(app_env="prod", database_url="postgresql://x", sheet_master_id="M")
    prod = Settings(app_env="prod", database_url="postgresql://x", sheet_master_id="M", sheet_caller_id="C")
    assert prod.target_sheets() == {"master": "M", "caller": "C"}


def test_dev_writes_only_the_staging_sheet() -> None:
    dev = Settings(app_env="dev", database_url="postgresql://x", sheet_staging_id="S")
    assert dev.target_sheets() == {"master": "S"}


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError, match="database_url"):
        get_settings()


def test_secrets_never_show_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2-secret@host:5432/db")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret-value")
    monkeypatch.setenv("GEMINI_API_KEY_BACKUP", "backup-secret-value")
    s = get_settings()
    text = repr(s) + str(s.model_dump())
    for secret in ("hunter2-secret", "gemini-secret-value", "backup-secret-value"):
        assert secret not in text
    assert s.gemini_api_key_backup is not None
    assert s.gemini_api_key_backup.get_secret_value() == "backup-secret-value"


def test_env_file_is_chosen_by_app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings_module, "ENV_FILE_DIR", tmp_path)
    monkeypatch.delenv("DATABASE_URL")
    (tmp_path / ".env.dev").write_text("DATABASE_URL=postgresql://dev-db\nASSOCIATE_NAME=Asha\nUNKNOWN_KEY=ignored\n")
    (tmp_path / ".env.prod").write_text(
        "APP_ENV=prod\nDATABASE_URL=postgresql://prod-db\nSHEET_MASTER_ID=M\nSHEET_CALLER_ID=C\n"
    )
    get_settings.cache_clear()
    dev = get_settings()
    assert dev.database_url.get_secret_value() == "postgresql://dev-db" and dev.associate_name == "Asha"
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    prod = get_settings()
    assert prod.app_env == "prod" and prod.database_url.get_secret_value() == "postgresql://prod-db"


def test_environment_wins_over_the_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings_module, "ENV_FILE_DIR", tmp_path)
    (tmp_path / ".env.dev").write_text("DATABASE_URL=postgresql://from-file\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env")
    get_settings.cache_clear()
    assert get_settings().database_url.get_secret_value() == "postgresql://from-env"


def test_service_account_from_json_or_file(tmp_path: Path) -> None:
    info = {"type": "service_account", "client_email": "bot@example.iam.gserviceaccount.com"}
    from_json = Settings(database_url="postgresql://x", google_service_account_json=json.dumps(info))
    assert from_json.service_account_info() == info
    path = tmp_path / "sa.json"
    path.write_text(json.dumps(info))
    from_file = Settings(database_url="postgresql://x", google_service_account_file=path)
    assert from_file.service_account_info() == info
    with pytest.raises(RuntimeError, match="GOOGLE_SERVICE_ACCOUNT"):
        Settings(database_url="postgresql://x").service_account_info()


def test_paths_point_inside_the_engine() -> None:
    s = Settings(database_url="postgresql://x")
    assert (s.segments_dir / "clinics-in.yaml").is_file()
    assert (s.config_dir / "scoring.yaml").is_file()
    assert s.user_agent == "NumentLeadBot/1.0 (+https://nument.in)"
