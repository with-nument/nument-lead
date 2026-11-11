"""Repository hygiene: rules the founder set for everything we ship."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DASHES = (chr(0x2013), chr(0x2014))  # en dash, em dash: never in docs or user-facing text
TEXT_SUFFIXES = {".py", ".sql", ".yaml", ".yml", ".toml", ".md", ".example"}
SKIP_PARTS = {".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".temp"}
SKIP_FILES = {"IMPLEMENTATION_PLAN.md"}  # the plan is checked when it is assembled


def _shipped_text_files() -> list[Path]:
    roots = [REPO / name for name in ("engine", "supabase", "docs", ".github")]
    files = [REPO / ".env.example"]
    for root in roots:
        if root.is_dir():
            files += [
                p
                for p in root.rglob("*")
                if p.is_file() and p.suffix in TEXT_SUFFIXES and not (SKIP_PARTS & set(p.relative_to(REPO).parts))
            ]
    return [p for p in files if p.is_file() and p.name not in SKIP_FILES]


def test_no_en_or_em_dashes_in_shipped_text() -> None:
    offenders = [
        f"{p.relative_to(REPO)}:{n}"
        for p in _shipped_text_files()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if any(d in line for d in DASHES)
    ]
    assert offenders == []


def test_no_local_env_files_are_tracked_by_the_examples() -> None:
    """Only .env.example may be committed; the real env files are ignored by git."""
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("**/.env.dev", "**/.env.prod", "**/.env.local", "!.env.example"):
        assert pattern in ignore, pattern
