"""Compare `nlead` output as plain words, the same on a laptop and in CI."""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BOX = re.compile(r"[─-╿]")


def plain(text: str) -> str:
    """Rich output as plain words: no colour codes, no panel borders, single spaces.

    Typer colours its output when GITHUB_ACTIONS or FORCE_COLOR is set, which splits flags like
    `--limit` with escape codes and wraps panels at 80 columns.
    """
    return " ".join(_BOX.sub(" ", _ANSI.sub("", text)).split())
