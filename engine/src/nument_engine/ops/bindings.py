"""Bindings to engine parts that other steps build: the AI router, polite HTTP, quote checks, scoring, lint.

The learning loop, the weekly audit and the eval harness call into Steps 4, 5, 10, 11 and 12. Every
binding is resolved here, lazily, so those callers stay testable with fakes and a missing piece fails with
`NotImplementedError` ("not built yet", exit code 2 on the command line) instead of a traceback.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

from ..logging import get_logger

log = get_logger()

Fetcher = Callable[[list[str]], dict[str, str]]  # urls -> main text of each page fetched successfully
QuoteChecker = Callable[[str, str], bool]  # (quote, page text) -> still there
Linter = Callable[[str, str], list[str]]  # (text, kind) -> problems
Scorer = Callable[..., Any]  # score_business(business, facts, signals, contacts, segment) -> ScoreResult


class TaskRunner(Protocol):
    """Runs one AI task through the router and returns its validated pydantic result."""

    def __call__(self, task: str, inputs: Mapping[str, Any], *, lead_id: str | None = None) -> Any: ...


def optional_attr(module: str, name: str) -> Any:
    """`module.name`, or None when the module or the attribute does not exist yet."""
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        return None


def _require(module: str, name: str, step: str) -> Any:
    found = optional_attr(module, name)
    if found is None:
        raise NotImplementedError(f"{module}.{name} is not built yet ({step})")
    return found


def stop_errors() -> tuple[type[BaseException], ...]:
    """Errors that mean "stop making AI calls in this run": the budget cap, or no provider left (Step 4.1.2)."""
    found = [
        optional_attr("nument_engine.budget", "BudgetExceeded"),
        optional_attr("nument_engine.llm.router", "AllProvidersDown"),
    ]
    return tuple(e for e in found if isinstance(e, type) and issubclass(e, BaseException))


def task_runner(rc: Any) -> TaskRunner:
    """A runner bound to this run (its id, per-run spend cap and cost rows), from `llm.router.for_run(rc)`."""
    factory = optional_attr("nument_engine.llm.router", "for_run")
    if factory is None:
        router_cls = optional_attr("nument_engine.llm.router", "Router")
        factory = getattr(router_cls, "for_run", None)
    if factory is None:
        raise NotImplementedError("nument_engine.llm.router.for_run(rc) is not built yet (Step 4)")
    router = factory(rc)

    def run(task: str, inputs: Mapping[str, Any], *, lead_id: str | None = None) -> Any:
        return router.run(task, dict(inputs), lead_id=lead_id)

    return run


def quote_checker() -> QuoteChecker:
    """`pipeline.verify.check_quote(quote, page_text) -> QuoteCheck(ok, score, why)` as a yes or no (Step 10.2)."""
    check = _require("nument_engine.pipeline.verify", "check_quote", "Step 10")

    def checker(quote: str, page_text: str) -> bool:
        result = check(quote, page_text)
        return bool(result.ok if hasattr(result, "ok") else result[0])

    return checker


def message_linter() -> Linter:
    """`pipeline.lint.lint(text, kind) -> problems` (Step 12.5)."""
    lint: Linter = _require("nument_engine.pipeline.lint", "lint", "Step 12")
    return lint


def business_scorer() -> Scorer:
    """`(business, facts, signals, contacts, segment) -> ScoreResult` with the weights in force (Step 11.6).

    Backed by `pipeline.score.Scorer`, which adds the config, exclusions, suppression and clock that
    `score_business` needs, and reads the weights on every call so `use_weights` blocks apply.
    """
    scorer_cls = _require("nument_engine.pipeline.score", "Scorer", "Step 11")
    scorer: Scorer = scorer_cls.load().score_rows
    return scorer


def _text_extractor() -> Callable[[str, str], str]:
    main_text = optional_attr("nument_engine.research.text", "main_text")
    if main_text is not None:

        def from_research(html: str, url: str) -> str:
            result = main_text(html, url)
            return str(result[0] if isinstance(result, tuple) else result or "")

        return from_research
    import trafilatura

    def from_trafilatura(html: str, url: str) -> str:
        return trafilatura.extract(html, url=url) or ""

    return from_trafilatura


def page_fetcher(source: str, min_gap_s: float = 2.0) -> Fetcher:
    """Fetch pages through the polite HTTP client (Step 5.2), never around it.

    Robots rules, the never-fetch list, honest identity and block handling all live in `http.py`. A blocked
    host is not tried again in the same call.
    """
    client_cls = _require("nument_engine.http", "PoliteClient", "Step 5")
    to_text = _text_extractor()

    async def fetch_all(urls: list[str]) -> dict[str, str]:
        client = client_cls(source=source, min_gap_s=min_gap_s)
        texts: dict[str, str] = {}
        stopped: set[str] = set()
        try:
            for url in urls:
                host = urlsplit(url).hostname or ""
                if host in stopped:
                    continue
                try:
                    result = await client.get(url)
                except Exception as exc:  # NeverFetch, SourceBlocked, network: skip this host for this call
                    log.warning("fetch.skipped", source=source, host=host, error=type(exc).__name__)
                    stopped.add(host)
                    continue
                if getattr(result, "state", "ok") == "ok" and getattr(result, "text", ""):
                    texts[url] = to_text(result.text, url)
        finally:
            closer = getattr(client, "aclose", None) or getattr(getattr(client, "client", None), "aclose", None)
            if closer is not None:
                await closer()
        return texts

    def fetch(urls: list[str]) -> dict[str, str]:
        return asyncio.run(fetch_all(urls))

    return fetch
