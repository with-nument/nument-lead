"""Test helpers: find and run a throwaway Postgres, and act as an API role like PostgREST does."""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

Conn = psycopg.Connection[dict[str, Any]]


def _major_version(bin_dir: Path) -> int:
    out = subprocess.run([str(bin_dir / "pg_ctl"), "--version"], capture_output=True, text=True, check=False).stdout
    match = re.search(r"\)\s*(\d+)", out)  # "pg_ctl (PostgreSQL) 17.11"
    return int(match.group(1)) if match else 0


def find_pg_bin() -> Path | None:
    """Folder with initdb and pg_ctl: NLEAD_PG_BIN, else the newest installed major version."""
    override = os.environ.get("NLEAD_PG_BIN")
    if override:
        path = Path(override).expanduser()
        return path if (path / "initdb").exists() and (path / "pg_ctl").exists() else None
    candidates: list[Path] = []
    for pattern in (
        "/opt/homebrew/opt/postgresql@*/bin",
        "/usr/local/opt/postgresql@*/bin",
        "/usr/lib/postgresql/*/bin",
    ):
        candidates += [Path(p) for p in glob.glob(pattern)]
    if pg_config := shutil.which("pg_config"):
        bindir = subprocess.run([pg_config, "--bindir"], capture_output=True, text=True, check=False).stdout.strip()
        if bindir:
            candidates.append(Path(bindir))
    if initdb := shutil.which("initdb"):
        candidates.append(Path(initdb).resolve().parent)
    usable = [c for c in candidates if (c / "initdb").exists() and (c / "pg_ctl").exists()]
    return max(usable, key=_major_version) if usable else None


def find_psql(pg_bin: Path | None) -> Path | None:
    """psql next to the server binaries, else on PATH."""
    if pg_bin is not None and (pg_bin / "psql").exists():
        return pg_bin / "psql"
    found = shutil.which("psql")
    return Path(found) if found else None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def _clean_env() -> dict[str, str]:
    """Environment for the Postgres tools without any PG* variables that could point them elsewhere."""
    return {k: v for k, v in os.environ.items() if not k.startswith("PG")}


@dataclass
class TempCluster:
    """A Postgres cluster in a temp folder, listening on 127.0.0.1 only, with no unix socket."""

    bin_dir: Path
    root: Path
    port: int = 0

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def dsn(self) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/postgres"

    def start(self) -> None:
        subprocess.run(
            [
                str(self.bin_dir / "initdb"),
                "-D",
                str(self.data_dir),
                "-U",
                "postgres",
                "-A",
                "trust",
                "-E",
                "UTF8",
                "--locale=C",
                "--no-sync",
            ],
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        last_error = ""
        for _ in range(3):  # a free port can be taken between choosing it and binding it
            self.port = _free_port()
            options = (
                f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories='' "
                "-c fsync=off -c synchronous_commit=off -c full_page_writes=off -c timezone=UTC"
            )
            result = subprocess.run(
                [
                    str(self.bin_dir / "pg_ctl"),
                    "-D",
                    str(self.data_dir),
                    "-l",
                    str(self.root / "server.log"),
                    "-o",
                    options,
                    "-w",
                    "-t",
                    "60",
                    "start",
                ],
                capture_output=True,
                text=True,
                env=_clean_env(),
                check=False,
            )
            if result.returncode == 0:
                return
            last_error = result.stderr + (self.root / "server.log").read_text(errors="replace")[-2000:]
        raise RuntimeError(f"could not start the test Postgres: {last_error}")

    def stop(self) -> None:
        subprocess.run(
            [str(self.bin_dir / "pg_ctl"), "-D", str(self.data_dir), "-m", "immediate", "-w", "stop"],
            capture_output=True,
            env=_clean_env(),
            check=False,
        )


@dataclass(frozen=True)
class RlsWorld:
    admin: str
    caller: str
    viewer: str
    business_id: str
    lead_id: str


def act_as(conn: psycopg.Connection[Any], role: str, user_id: str | None = None) -> None:
    """Switch the current transaction to an API role with the given user's JWT claims (like PostgREST)."""
    conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
    claims = json.dumps({"sub": user_id, "role": role}) if user_id else ""
    conn.execute("select set_config('request.jwt.claims', %s, true)", [claims])
