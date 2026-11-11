"""JSON logs with run id and run kind on every line (structlog).

This module is imported as `nument_engine.logging`; it imports the standard library module as
`stdlib_logging` so the two never shadow each other.
"""

from __future__ import annotations

import logging as stdlib_logging
import sys

import structlog
from structlog.typing import FilteringBoundLogger

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


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
