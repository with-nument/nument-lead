"""JSON logs with run id and run kind on every line (structlog).

This module is imported as `nument_engine.logging`; it imports the standard library module as
`stdlib_logging` so the two never shadow each other.
"""

from __future__ import annotations

import logging as stdlib_logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.typing import FilteringBoundLogger

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# The repository and its Actions logs are public, so personal data never reaches a log line: email addresses
# keep their first letter and domain (j***@acme.com), phone numbers their first 3 and last 2 characters.
_EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
_PHONE = re.compile(r"(?<![\w:.+-])\+?\d[\d ().-]{6,}\d(?![\w:-])")
_UNMASKED_KEYS = frozenset({"timestamp", "run_id", "run_kind", "env", "level", "logger"})


def _mask_phone(match: re.Match[str]) -> str:
    text = match.group(0)
    digits = sum(ch.isdigit() for ch in text)
    if digits < (8 if text.startswith("+") else 9) or digits > 15:
        return text  # a date, a count or an id, not a phone number
    return f"{text[:3]}{'*' * max(len(text) - 5, 1)}{text[-2:]}"


def mask_text(text: str) -> str:
    """The text with email addresses and phone numbers masked."""
    if "@" in text:
        text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    return _PHONE.sub(_mask_phone, text)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: _mask_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_mask_value(v) for v in value]  # rendered as a JSON array either way
    return value


def mask_personal_data(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor: masks emails and phone numbers in every value (and in exception text)."""
    for key, value in event_dict.items():
        if key not in _UNMASKED_KEYS:
            event_dict[key] = _mask_value(value)
    return event_dict


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog once per process. JSON in CI, readable console output with --pretty-logs."""
    level = level.upper()
    if level not in LEVELS:
        raise ValueError(f"log level must be one of {', '.join(LEVELS)}, got {level!r}")
    numeric = getattr(stdlib_logging, level)
    stdlib_logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric)
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        mask_personal_data,
    ]
    processors.append(structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        cache_logger_on_first_use=True,
    )


def bind_run(run_id: str, kind: str, env: str) -> None:
    """Attach run id, run kind and environment to every log line of this run."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id, run_kind=kind, env=env)


def get_logger(name: str = "nlead") -> FilteringBoundLogger:
    """A structlog logger. Usage: `log.info("event.name", key=value)`."""
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger
