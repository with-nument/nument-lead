"""Encrypted backups (Step 14.5.6): tool discovery, no secrets on command lines, encryption round trip, retention."""

from __future__ import annotations

import datetime as dt
import gzip
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from nument_engine.ops import backup
from nument_engine.settings import Settings

URL = "postgresql://postgres.abcd:s3cret-pass@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def gnupg_home(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A throwaway GnuPG home with a short path (the agent socket path is limited to about 100 characters),
    so the tests never touch the developer's own keyring."""
    home = Path(tempfile.mkdtemp(prefix="gpg"))
    home.chmod(0o700)
    monkeypatch.setenv("GNUPGHOME", str(home))
    yield home
    if shutil.which("gpgconf"):
        subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"], capture_output=True, check=False)
    shutil.rmtree(home, ignore_errors=True)


def test_pg_env_keeps_the_password_off_the_command_line() -> None:
    env = backup.pg_env(URL)
    assert env["PGPASSWORD"] == "s3cret-pass" and env["PGHOST"].endswith("pooler.supabase.com")
    assert env["PGUSER"] == "postgres.abcd" and env["PGPORT"] == "5432" and env["PGSSLMODE"] == "require"
    args = backup.pg_dump_args("/usr/bin/pg_dump")
    assert "--data-only" in args and "--schema=public" in args
    assert not [a for a in args if "s3cret" in a or "postgresql://" in a]


def test_find_pg_dump_picks_one_at_least_as_new_as_the_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = _script(tmp_path / "pg16", 'echo "pg_dump (PostgreSQL) 16.15 (Homebrew)"\n')
    new = _script(tmp_path / "pg17", 'echo "pg_dump (PostgreSQL) 17.11"\n')
    monkeypatch.delenv("NLEAD_PG_DUMP", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert backup.pg_dump_major(str(old)) == 16
    assert backup.find_pg_dump(17, candidates=(str(old), str(new))) == str(new)
    with pytest.raises(backup.BackupError, match="no pg_dump 17"):
        backup.find_pg_dump(17, candidates=(str(old),))
    monkeypatch.setenv("NLEAD_PG_DUMP", str(new))
    assert backup.find_pg_dump(17, candidates=()) == str(new)


@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg is not installed")
def test_dump_streams_through_gzip_and_gpg(tmp_path: Path, gnupg_home: Path) -> None:
    home = gnupg_home
    fake_dump = _script(tmp_path / "pg_dump", "echo \"COPY public.leads (id) FROM stdin;\"\necho '\\\\.'\n")
    settings = Settings(database_url=SecretStr(URL), backup_passphrase=SecretStr("correct horse battery staple"))
    out = tmp_path / "out" / "db.sql.gz.gpg"
    gpg = shutil.which("gpg")
    assert gpg is not None
    size = backup.dump(settings, str(fake_dump), gpg, out)
    assert size == out.stat().st_size > 0 and not out.with_suffix(out.suffix + ".part").exists()
    assert b"COPY public.leads" not in out.read_bytes()  # encrypted
    plain = subprocess.run(
        [gpg, "--homedir", str(home), "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", "correct horse battery staple",
         "--decrypt", str(out)],
        capture_output=True, check=True, env={**os.environ, "GNUPGHOME": str(home)},
    ).stdout  # fmt: skip
    text = gzip.decompress(plain).decode()
    assert text.startswith("-- Nument Leads data backup") and "SET session_replication_role = replica;" in text
    assert "COPY public.leads (id) FROM stdin;" in text and text.rstrip().endswith(
        "SET session_replication_role = DEFAULT;"
    )


@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg is not installed")
def test_a_failed_dump_leaves_no_file(tmp_path: Path, gnupg_home: Path) -> None:
    broken = _script(tmp_path / "pg_dump", "echo 'connection failed: password=hunter2' >&2\nexit 1\n")
    settings = Settings(database_url=SecretStr(URL), backup_passphrase=SecretStr("x" * 20))
    out = tmp_path / "db.sql.gz.gpg"
    gpg = shutil.which("gpg")
    assert gpg is not None
    with pytest.raises(backup.BackupError, match="pg_dump failed") as err:
        backup.dump(settings, str(broken), gpg, out)
    assert "hunter2" not in str(err.value)
    assert not out.exists() and not list(tmp_path.glob("*.part"))


def test_retention_keeps_eight_weeks_and_the_newest_two() -> None:
    now = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)

    def obj(days: int) -> dict[str, str]:
        return {"name": f"nument-db-{days}.sql.gz.gpg", "created_at": (now - dt.timedelta(days=days)).isoformat()}

    objects = [obj(1), obj(8), obj(50), obj(57), obj(90)]
    assert [o["name"] for o in backup.expired(objects, now)] == ["nument-db-57.sql.gz.gpg", "nument-db-90.sql.gz.gpg"]
    assert backup.expired([obj(100), obj(200)], now) == []  # never the newest two
