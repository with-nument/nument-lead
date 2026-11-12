"""Encrypted weekly backup of the data in the public schema (Step 2.14, 14.5.6, A.13.5 rule 12).

    pg_dump --data-only --schema=public  ->  gzip  ->  gpg --symmetric (AES256)  ->  file
    file  ->  Supabase Storage, private bucket `backups` (service role only); dumps older than 8 weeks deleted

The schema lives in `supabase/migrations`, so the dump holds data only. Nothing unencrypted touches the disk:
the dump streams through gzip into gpg, and the passphrase reaches gpg through a pipe, never the command line.
The database password reaches pg_dump through its environment, never the command line either.

Restore (practise once on a spare project, Step 21):
    1. New Supabase project; run the migrations (`nlead db migrate` with that DATABASE_URL).
    2. gpg --decrypt nument-db-YYYYMMDD-HHMM.sql.gz.gpg | gunzip | psql "$DATABASE_URL"
       The dump starts with `SET session_replication_role = replica`, so triggers do not fire and rows load in
       any order. Auth users are not in the dump: recreate them as in Step 2.9.1.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import zlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

import httpx
from psycopg.conninfo import conninfo_to_dict

from .. import db
from ..logging import get_logger
from ..pipeline.runs import RunContext
from ..settings import Settings, get_settings

log = get_logger()

BUCKET: Final = "backups"
KEEP_WEEKS: Final = 8
KEEP_AT_LEAST: Final = 2  # never delete the newest two, however old
UPLOAD_LIMIT_BYTES: Final = 50 * 1024 * 1024  # the bucket's file limit (0003_rls.sql) = the free-plan upload limit
HEADER: Final = b"-- Nument Leads data backup (public schema). Restore after running the migrations.\nSET session_replication_role = replica;\n"
FOOTER: Final = b"\nSET session_replication_role = DEFAULT;\n"
PG_DUMP_CANDIDATES: Final = (
    "/opt/homebrew/opt/postgresql@17/bin/pg_dump",
    "/usr/local/opt/postgresql@17/bin/pg_dump",
    "/usr/lib/postgresql/17/bin/pg_dump",
    "/opt/homebrew/opt/postgresql@18/bin/pg_dump",
    "/usr/lib/postgresql/18/bin/pg_dump",
)


class BackupError(RuntimeError):
    """The dump, the encryption or the upload failed. Messages never contain secrets."""


def run(rc: RunContext, *, out: Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    server_major = int(db.scalar("select current_setting('server_version_num')::int / 10000") or 0)
    pg_dump = find_pg_dump(server_major)
    gpg = shutil.which("gpg")
    if not gpg:
        raise BackupError("gpg is not installed")
    if not settings.backup_passphrase:
        raise BackupError("BACKUP_PASSPHRASE is not set")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M")
    name = f"nument-db-{stamp}.sql.gz.gpg"
    target = out or (settings.cache_dir / "backups" / name)
    storage = Storage.from_settings(settings)
    if rc.opts.dry_run:
        existing = storage.list_backups() if storage else []
        return {"dry_run": True, "pg_dump": pg_dump, "server_major": server_major, "would_write": str(target),
                "stored_backups": len(existing), "would_delete": [o["name"] for o in expired(existing, dt.datetime.now(dt.UTC))]}  # fmt: skip
    size = dump(settings, pg_dump, gpg, target)
    stats: dict[str, Any] = {"file": str(target), "bytes": size, "pg_dump": pg_dump, "uploaded": False}
    if storage is None:
        log.warning("backup.no_storage", reason="SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing; kept the file only")
        return stats
    if size > UPLOAD_LIMIT_BYTES:
        log.warning("backup.too_big_for_bucket", bytes=size, limit=UPLOAD_LIMIT_BYTES)
        stats["upload_skipped"] = "over the bucket limit; the workflow artifact keeps the copy"
        return stats
    storage.upload(target.name, target)
    stats["uploaded"] = True
    old = expired(storage.list_backups(), dt.datetime.now(dt.UTC))
    if old:
        storage.delete([o["name"] for o in old])
    stats["deleted_old"] = len(old)
    log.info("backup.done", **stats)
    return stats


# ---------------------------------------------------------------------------
# pg_dump
# ---------------------------------------------------------------------------
def pg_dump_major(path: str) -> int:
    out = subprocess.run([path, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.search(r"\)\s*(\d+)", out)  # "pg_dump (PostgreSQL) 17.11" or "... 16.15 (Homebrew)"
    return int(match.group(1)) if match else 0


def find_pg_dump(server_major: int, candidates: Sequence[str] = PG_DUMP_CANDIDATES) -> str:
    """A pg_dump at least as new as the server: NLEAD_PG_DUMP, then known install paths, then PATH."""
    options = [os.environ.get("NLEAD_PG_DUMP", ""), *candidates, shutil.which("pg_dump") or ""]
    seen = set()
    for path in options:
        if not path or path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        if pg_dump_major(path) >= server_major:
            return path
    raise BackupError(
        f"no pg_dump {server_major} or newer found (pg_dump refuses a newer server). "
        "Install postgresql-client-17, or set NLEAD_PG_DUMP to its pg_dump."
    )


def pg_env(database_url: str) -> dict[str, str]:
    """libpq environment for pg_dump, so the password never appears in the process list."""
    parts = conninfo_to_dict(database_url)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    mapping = {"host": "PGHOST", "port": "PGPORT", "user": "PGUSER", "password": "PGPASSWORD", "dbname": "PGDATABASE", "sslmode": "PGSSLMODE"}  # fmt: skip
    for key, var in mapping.items():
        if parts.get(key):
            env[var] = str(parts[key])
    env.setdefault("PGSSLMODE", "require")
    env["PGCONNECT_TIMEOUT"] = "20"
    return env


def pg_dump_args(pg_dump: str) -> list[str]:
    return [
        pg_dump,
        "--data-only",
        "--schema=public",
        "--no-owner",
        "--no-privileges",
        "--format=plain",
        "--quote-all-identifiers",
    ]


def dump(settings: Settings, pg_dump: str, gpg: str, target: Path) -> int:
    """Stream pg_dump -> gzip -> gpg into `target`. Returns the size in bytes; removes a partial file on failure."""
    assert settings.backup_passphrase is not None
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    read_fd, write_fd = os.pipe()
    gpg_cmd = [gpg, "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback", "--symmetric", "--cipher-algo", "AES256",
               "--passphrase-fd", str(read_fd), "--output", str(tmp)]  # fmt: skip
    try:
        with subprocess.Popen(gpg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(read_fd,)) as enc:
            os.close(read_fd)
            os.write(write_fd, settings.backup_passphrase.get_secret_value().encode() + b"\n")
            os.close(write_fd)
            write_fd = -1
            with subprocess.Popen(
                pg_dump_args(pg_dump), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=pg_env(settings.database_url.get_secret_value()),
            ) as src:  # fmt: skip
                assert enc.stdin is not None and src.stdout is not None
                gz = zlib.compressobj(9, zlib.DEFLATED, 31)  # wbits 31 = gzip container
                enc.stdin.write(gz.compress(HEADER))
                for chunk in iter(lambda: src.stdout.read(1 << 20), b""):  # type: ignore[union-attr]
                    enc.stdin.write(gz.compress(chunk))
                enc.stdin.write(gz.compress(FOOTER) + gz.flush())
                enc.stdin.close()
                dump_err = src.stderr.read().decode(errors="replace") if src.stderr else ""
            enc_err = enc.stderr.read().decode(errors="replace") if enc.stderr else ""
        if src.returncode != 0:
            raise BackupError(f"pg_dump failed ({src.returncode}): {_scrub(dump_err)[-500:]}")
        if enc.returncode != 0:
            raise BackupError(f"gpg failed ({enc.returncode}): {_scrub(enc_err)[-500:]}")
        tmp.replace(target)
        return target.stat().st_size
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if write_fd != -1:
            os.close(write_fd)


def _scrub(text: str) -> str:
    """Drop anything that looks like a connection string or password from tool errors."""
    return re.sub(r"(postgres(?:ql)?://)\S+", r"\1***", re.sub(r"password\S*", "password=***", text, flags=re.I))


# ---------------------------------------------------------------------------
# Supabase Storage (REST, service role)
# ---------------------------------------------------------------------------
class Storage:
    def __init__(self, url: str, key: str) -> None:
        self.base = url.rstrip("/") + "/storage/v1"
        self.headers = {"Authorization": f"Bearer {key}", "apikey": key}

    @classmethod
    def from_settings(cls, settings: Settings) -> Storage | None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            return None
        return cls(settings.supabase_url, settings.supabase_service_role_key.get_secret_value())

    def _check(self, resp: httpx.Response, what: str) -> None:
        if resp.status_code >= 400:
            raise BackupError(f"storage {what}: HTTP {resp.status_code}: {resp.text[:200]}")

    def upload(self, name: str, path: Path) -> None:
        with path.open("rb") as fh:
            resp = httpx.post(
                f"{self.base}/object/{BUCKET}/{name}",
                headers={**self.headers, "Content-Type": "application/octet-stream", "x-upsert": "false"},
                content=fh.read(),
                timeout=300,
            )
        self._check(resp, "upload")

    def list_backups(self) -> list[dict[str, Any]]:
        resp = httpx.post(
            f"{self.base}/object/list/{BUCKET}",
            headers=self.headers,
            json={"prefix": "", "limit": 1000, "offset": 0, "sortBy": {"column": "created_at", "order": "desc"}},
            timeout=60,
        )
        self._check(resp, "list")
        return [o for o in resp.json() if str(o.get("name", "")).startswith("nument-db-")]

    def delete(self, names: list[str]) -> None:
        resp = httpx.request(
            "DELETE", f"{self.base}/object/{BUCKET}", headers=self.headers, json={"prefixes": names}, timeout=60
        )
        self._check(resp, "delete")


def expired(
    objects: Iterable[dict[str, Any]], now: dt.datetime, weeks: int = KEEP_WEEKS, keep: int = KEEP_AT_LEAST
) -> list[dict[str, Any]]:
    """Backups older than `weeks`, never touching the newest `keep`."""

    def created(o: dict[str, Any]) -> dt.datetime:
        raw = str(o.get("created_at") or "")
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return now  # unknown age: keep it

    ordered = sorted(objects, key=created, reverse=True)
    cutoff = now - dt.timedelta(weeks=weeks)
    return [o for o in ordered[keep:] if created(o) < cutoff]
