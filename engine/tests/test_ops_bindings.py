"""Bindings to stages built by other steps: missing parts fail as "not built yet", present ones are used."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest

from nument_engine.ops import bindings


def fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: Any) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


def test_optional_attr() -> None:
    assert bindings.optional_attr("nument_engine.models", "STAGES")
    assert bindings.optional_attr("nument_engine.models", "missing") is None
    assert bindings.optional_attr("nument_engine.no_such_module", "x") is None


def test_missing_parts_say_which_step_builds_them(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module(monkeypatch, "nument_engine.pipeline.verify")
    fake_module(monkeypatch, "nument_engine.pipeline.score")
    fake_module(monkeypatch, "nument_engine.pipeline.message")
    fake_module(monkeypatch, "nument_engine.llm.router")
    fake_module(monkeypatch, "nument_engine.http")
    for make, step in (
        (bindings.quote_checker, "Step 10"),
        (bindings.business_scorer, "Step 11"),
        (bindings.message_linter, "Step 12"),
        (lambda: bindings.task_runner(None), "Step 4"),
        (lambda: bindings.page_fetcher("audit"), "Step 5"),
    ):
        with pytest.raises(NotImplementedError, match=step):
            make()


def test_present_parts_are_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module(monkeypatch, "nument_engine.pipeline.verify", check_quote=lambda q, t: (q in t, 100, "exact"))
    assert bindings.quote_checker()("hello", "say hello") is True

    class Router:
        def __init__(self, rc: Any) -> None:
            self.rc = rc

        def run(self, task: str, inputs: dict[str, Any], *, lead_id: str | None = None) -> tuple[str, Any, Any, Any]:
            return task, inputs, lead_id, self.rc

    fake_module(monkeypatch, "nument_engine.llm.router", for_run=Router)
    run = bindings.task_runner("rc")
    assert run("judge_lead", {"a": 1}, lead_id="L1") == ("judge_lead", {"a": 1}, "L1", "rc")


def test_stop_errors_only_lists_exception_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    class BudgetExceeded(Exception):
        pass

    fake_module(monkeypatch, "nument_engine.budget", BudgetExceeded=BudgetExceeded)
    fake_module(monkeypatch, "nument_engine.llm.router", AllProvidersDown="not a class")
    assert bindings.stop_errors() == (BudgetExceeded,)


def test_page_fetcher_uses_the_polite_client_and_skips_failing_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    @dataclass
    class Result:
        state: str
        text: str

    class PoliteClient:
        closed = False

        def __init__(self, source: str, min_gap_s: float) -> None:
            assert source == "audit" and min_gap_s == 2.0

        async def get(self, url: str) -> Result:
            calls.append(url)
            if "blocked" in url:
                raise RuntimeError("SourceBlocked")
            return Result("ok", "<html><body><p>Open daily, call 98200 12345</p></body></html>")

        async def aclose(self) -> None:
            PoliteClient.closed = True

    fake_module(monkeypatch, "nument_engine.http", PoliteClient=PoliteClient)
    fake_module(
        monkeypatch, "nument_engine.research.text", main_text=lambda html, url: ("Open daily, call 98200 12345", [])
    )
    fetch = bindings.page_fetcher("audit")
    urls = ["https://blocked.example.com/", "https://blocked.example.com/contact", "https://ok.example.com/"]
    texts = fetch(urls)
    assert texts == {"https://ok.example.com/": "Open daily, call 98200 12345"}
    assert calls == ["https://blocked.example.com/", "https://ok.example.com/"]  # no second try at a failed host
    assert PoliteClient.closed
