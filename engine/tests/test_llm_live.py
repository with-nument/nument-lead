"""Live end-to-end check of the AI router against the real Gemini API (Step 4.15). Skipped in CI.

Run it at build time and after any model or prompt change:

    uv run pytest -m live tests/test_llm_live.py -s

It reads GEMINI_API_KEY and GEMINI_API_KEY_BACKUP from the environment or from engine/.env.dev, keeps OpenAI
switched off (a placeholder OpenAI key is set, so the fallback is exercised for the right reason), writes only
to the throwaway test database, and stops paid calls at LIVE_CAP_INR. It proves:

1. structured output on the primary model of every task, validated by the canonical models;
2. write_message falls back from the disabled OpenAI primary to Gemini, with fallback_from and an activity;
3. a repeated call is served from the cache;
4. grounded search returns citations and logs its queries as provider google_search;
5. a tiny Gemini Batch job submits, and is collected if it finishes within BATCH_WAIT_S (else it is cancelled).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator

import pytest

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.llm import batch, health
from nument_engine.llm.router import Router
from nument_engine.models import FactsExtraction, PublicAskResults
from nument_engine.settings import ENGINE_DIR

from .llm_fakes import llm_db_fixture, new_lead, new_run  # noqa: F401

LIVE_CAP_INR = 30.0
BATCH_WAIT_S = 15 * 60
KEY_NAMES = ("GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP")


def _real_keys() -> dict[str, str]:
    found = {name: os.environ.get(f"NLEAD_LIVE_{name}", "") for name in KEY_NAMES}
    env_file = ENGINE_DIR / ".env.dev"
    if not found["GEMINI_API_KEY"] and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if match and match.group(1) in KEY_NAMES:
                found[match.group(1)] = match.group(2).strip().strip("'\"")
    return {k: v for k, v in found.items() if v}


@pytest.fixture
def live_router(llm_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Router]:
    keys = _real_keys()
    if "GEMINI_API_KEY" not in keys:
        pytest.skip("needs GEMINI_API_KEY (environment NLEAD_LIVE_GEMINI_API_KEY or engine/.env.dev)")
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-placeholder-openai-is-switched-off")
    settings_module.get_settings.cache_clear()
    db.set_setting("providers_enabled", {"gemini": True, "openai": False})
    run_id = new_run()
    yield Router(run_id=run_id, max_spend_inr=LIVE_CAP_INR, stats={})
    settings_module.get_settings.cache_clear()


def _spent(run_id: str) -> float:
    return float(db.scalar("select coalesce(sum(usd), 0) from public.costs where run_id = %s", [run_id]) or 0) * 88


@pytest.mark.live
def test_live_gemini_end_to_end(live_router: Router) -> None:
    assert live_router.run_id is not None
    try:
        _end_to_end(live_router)
    finally:  # the exact spend is printed even when a step fails (the test database is thrown away)
        print(f"TOTAL live spend: ₹{_spent(live_router.run_id):.4f} (cap ₹{LIVE_CAP_INR:.0f})")


def _end_to_end(router: Router) -> None:
    assert router.run_id is not None
    assert "openai" in router.providers and not router.availability.usable("openai")

    # 1. Every task's primary model, structured output validated by the canonical models.
    tasks = sorted(t for t in router.registry.tasks if t != "grounded_search")
    report = health.llm_smoke(router, primaries_only=True, tasks=tasks)
    print("\n" + "\n".join(health.format_smoke(report)))
    assert report.failures == 0
    ran = {r.task for r in report.rows if r.ok}
    assert ran == set(tasks) - {"write_message"}  # its primary is OpenAI, which is off
    write_row = next(r for r in report.rows if r.task == "write_message")
    assert write_row.ok is None and "providers_enabled.openai = false" in write_row.detail

    # 2. Fallback from the disabled OpenAI primary to Gemini, recorded on the lead and in costs.
    lead_id = new_lead()
    res = router.run_result("write_message", health.SMOKE_INPUTS["write_message"], lead_id=lead_id)
    print(f"write_message: {res.tag} fallback_from={res.fallback_from} inr={res.inr:.4f}")
    print(f"  message: {res.output.message}")
    assert res.provider == "gemini" and res.fallback_from == "openai:gpt-5-mini"
    assert db.scalar("select count(*) from public.activities where lead_id = %s and type = 'ai_output'", [lead_id]) == 1
    assert (
        db.scalar(
            "select count(*) from public.costs where run_id = %s and task = 'write_message' "
            "and fallback_from = 'openai:gpt-5-mini'",
            [router.run_id],
        )
        == 1
    )

    # 3. The cache: classify_signal again, no new paid call.
    again = router.run_result("classify_signal", health.SMOKE_INPUTS["classify_signal"])
    assert not again.cached  # the smoke run bypassed the cache, so this one fills it
    cached = router.run_result("classify_signal", health.SMOKE_INPUTS["classify_signal"])
    assert cached.cached and cached.inr == 0 and cached.output == again.output

    # 4. Grounded search: citations and google_search query rows.
    found = router.run_result("grounded_search", health.SMOKE_INPUTS["grounded_search"], use_cache=False)
    assert isinstance(found.output, PublicAskResults)
    assert found.grounding is not None and found.grounding["sources"] and found.grounding["queries"]
    print(f"grounded_search: {len(found.output.items)} items, {len(found.grounding['queries'])} queries, "
          f"{len(found.grounding['sources'])} sources, inr={found.inr:.4f}")  # fmt: skip
    for item in found.output.items[:3]:
        print(f"  - {item.poster_business} | {item.need} | {item.url}")
    queries = db.scalar(
        "select coalesce(sum(calls), 0) from public.costs where run_id = %s and provider = 'google_search'",
        [router.run_id],
    )
    assert queries == len(found.grounding["queries"])

    # 5. A tiny Gemini Batch job.
    items = []
    for n in range(3):
        inputs = dict(health.SMOKE_INPUTS["extract_facts"])
        inputs["business_name"] = f"Sunrise Dental Clinic {n + 1}"
        items.append(batch.BatchItem(key=f"extract_facts:live-{n + 1}", inputs=inputs))
    submitted = batch.submit(router, "extract_facts", items, display_name="nlead:live-test")
    assert len(submitted.jobs) == 1 and submitted.submitted_keys == [i.key for i in items]
    job = submitted.jobs[0]
    print(f"batch: {job.provider_batch_id} on {job.model}, reserved ₹{job.reserved_inr:.4f}")
    started = time.monotonic()
    collected = batch.collect(router, "extract_facts", max_wait_s=BATCH_WAIT_S, poll_s=20)
    waited = time.monotonic() - started
    if collected.pending:
        cancelled = batch.cancel_open(router, "extract_facts")
        print(f"batch still running after {waited:.0f}s: cancelled {cancelled}")
    else:
        print(f"batch collected after {waited:.0f}s: {batch.describe(collected)}")
        assert collected.failed_keys == []
        assert {r.key for r in collected.results} == {i.key for i in items}
        assert all(r.ok and isinstance(r.output, FactsExtraction) for r in collected.results)
        assert db.scalar("select status from public.llm_batches where id = %s", [job.llm_batch_id]) == "completed"

    print(f"run stats: {router.stats}")
    assert _spent(router.run_id) < LIVE_CAP_INR
