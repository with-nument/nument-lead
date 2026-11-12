"""Batch submit and collect (Step 4.10.2, 4.13 tests 13 and 16; Steps 9.13 and 9.14)."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine import db
from nument_engine.budget import estimate_tokens, llm_cost_usd
from nument_engine.llm import batch, store
from nument_engine.llm.health import SMOKE_INPUTS
from nument_engine.llm.router import PROMPT_OVERHEAD_TOKENS
from nument_engine.llm.types import BatchRow, LLMResponse, Usage
from nument_engine.models import FactsExtraction

from .llm_fakes import FakeClock, FakeProvider, err, llm_db_fixture, make_router, reply  # noqa: F401
from .llm_outputs import OUTPUTS

KEYS = ["extract_facts:b1", "extract_facts:b2", "extract_facts:b3"]


def _items(keys: list[str] = KEYS) -> list[batch.BatchItem]:
    out = []
    for key in keys:
        inputs = dict(SMOKE_INPUTS["extract_facts"])
        inputs["business_name"] = f"Clinic {key}"
        out.append(batch.BatchItem(key=key, inputs=inputs))
    return out


def _ok_row(key: str, model: str = "gemini-3.8-flash") -> BatchRow:
    resp = LLMResponse(
        text=OUTPUTS["extract_facts"].model_dump_json(),
        usage=Usage(input_tokens=8000, output_tokens=1500),
        provider="gemini",
        model=model,
        finish_reason="stop",
    )
    return BatchRow(key=key, response=resp, error=None)


def _batches() -> list[dict[str, Any]]:
    return db.fetch_all("select * from public.llm_batches order by submitted_at")


def test_extraction_batch_goes_to_gemini_when_openai_is_off(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    openai = FakeProvider("openai")
    router = make_router({"gemini": gemini, "openai": openai})
    result = batch.submit(router, "extract_facts", _items())

    assert len(result.jobs) == 1 and result.submitted_keys == KEYS
    job = result.jobs[0]
    assert (job.provider, job.model) == ("gemini", "gemini-3.8-flash") and openai.batches == {}
    sent = gemini.batches[job.provider_batch_id]
    assert [r.key for r in sent.reqs] == KEYS
    assert all(r.schema is FactsExtraction and r.thinking == "low" for r in sent.reqs)
    assert "Clinic extract_facts:b2" in sent.reqs[1].user

    rows = _batches()
    assert len(rows) == 1 and rows[0]["status"] == "submitted" and rows[0]["item_count"] == 3
    reserved = db.scalar(
        "select reserved_inr from public.llm_batch_reservations where llm_batch_id = %s", [job.llm_batch_id]
    )
    assert float(reserved) == pytest.approx(job.reserved_inr) and job.reserved_inr > 0
    assert store.items_in_flight("extract_facts", KEYS) == set(KEYS)
    meta = store.batch_meta(job.llm_batch_id)
    assert meta is not None and meta["model"] == "gemini-3.8-flash" and meta["prompt_version"] == 1
    assert meta["fallback_from"] is None and meta["keys"] == KEYS


def test_items_already_in_a_live_batch_are_never_submitted_twice(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini})
    batch.submit(router, "extract_facts", _items())
    again = batch.submit(router, "extract_facts", _items([*KEYS, "extract_facts:b4"]))
    assert again.in_flight == KEYS
    assert again.submitted_keys == ["extract_facts:b4"]
    assert len(gemini.batches) == 2


def test_duplicate_keys_in_one_call_are_dropped(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    result = batch.submit(make_router({"gemini": gemini}), "extract_facts", _items([KEYS[0], KEYS[0]]))
    assert result.submitted_keys == [KEYS[0]]


def test_dry_run_never_submits(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    result = batch.submit(make_router({"gemini": gemini}, dry_run=True), "extract_facts", _items())
    assert result.dry_run and result.deferred == KEYS and gemini.batches == {} and _batches() == []


def test_failed_submissions_fall_back_to_a_few_sync_calls(llm_db: str) -> None:
    """Test 13: no batch provider works, so up to N items run as sync calls and the rest stay queued."""
    gemini = FakeProvider("gemini", [reply(OUTPUTS["extract_facts"]), reply(OUTPUTS["extract_facts"])])
    gemini.submit_errors = [err("bad_request", "batch refused")] * 3  # flash, flash_prev and lite all refuse
    router = make_router({"gemini": gemini})
    result = batch.submit(router, "extract_facts", _items(), sync_fallback_limit=2)
    assert result.jobs == []
    assert [r.key for r in result.sync_results] == KEYS[:2] and all(r.ok and r.sync for r in result.sync_results)
    assert result.sync_results[0].tag == "gemini:gemini-3.8-flash#extract_facts.v1"
    assert result.deferred == KEYS[2:]
    assert router.stats["batches"]["extract_facts"] == {"submitted": 0, "sync": 2, "deferred": 1}


def test_a_failing_model_hands_the_batch_to_the_next_one(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    gemini.submit_errors = [err("not_found", "model not found")]
    result = batch.submit(make_router({"gemini": gemini}), "extract_facts", _items())
    assert len(result.jobs) == 1 and result.jobs[0].model == "gemini-3.6-flash"
    assert store.batch_meta(result.jobs[0].llm_batch_id)["fallback_from"] == "gemini:gemini-3.8-flash"  # type: ignore[index]


def test_budget_limits_how_many_items_are_submitted(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini})
    _, system, user = router.render("extract_facts", _items()[0].inputs)
    tokens = estimate_tokens(system) + estimate_tokens(user) + PROMPT_OVERHEAD_TOKENS
    one = router.budget.estimate_llm_inr("gemini-3.8-flash", tokens, 2500, batch=True)
    db.set_setting("daily_cap_inr", 2.5 * one / 0.95)  # room for two items under the 95% limit
    router.budget.reload_settings()  # settings are read once per run; this test changes them mid-run
    result = batch.submit(router, "extract_facts", _items())
    assert len(result.submitted_keys) == 2 and result.deferred == KEYS[2:]
    assert any("budget" in r for r in result.reasons)


def test_collect_ingests_results_logs_batch_costs_and_releases_the_reservation(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini}, clock=clock)
    job = batch.submit(router, "extract_facts", _items()).jobs[0]
    fake = gemini.batches[job.provider_batch_id]
    fake.state, fake.rows = "succeeded", [_ok_row(k) for k in KEYS]

    out = batch.collect(router, "extract_facts")
    assert [r.key for r in out.results] == KEYS and all(r.ok and not r.sync for r in out.results)
    assert isinstance(out.results[0].output, FactsExtraction)
    assert out.results[0].tag == "gemini:gemini-3.8-flash#extract_facts.v1"
    assert out.failed_keys == [] and out.pending == []

    row = _batches()[0]
    assert row["status"] == "completed" and row["completed_at"] is not None
    assert db.scalar("select bool_and(released) from public.llm_batch_reservations") is True
    assert store.items_in_flight("extract_facts", KEYS) == set()
    assert store.batch_meta(job.llm_batch_id) is None
    costs = db.fetch_all("select * from public.costs where at = %s and task = 'extract_facts'", [clock()])
    assert len(costs) == 3
    expected = llm_cost_usd("gemini-3.8-flash", 8000, 1500, batch=True, on=clock().date())
    assert float(costs[0]["usd"]) == pytest.approx(expected, abs=1e-6)
    assert router.budget.reserved_inr() == 0


def test_invalid_item_gets_one_sync_retry_when_inputs_can_be_rebuilt(llm_db: str) -> None:
    gemini = FakeProvider("gemini", [reply(OUTPUTS["extract_facts"])])
    router = make_router({"gemini": gemini})
    job = batch.submit(router, "extract_facts", _items()).jobs[0]
    fake = gemini.batches[job.provider_batch_id]
    bad = BatchRow(
        key=KEYS[1], response=LLMResponse("not json", Usage(10, 10), "gemini", "gemini-3.8-flash"), error=None
    )
    fake.state = "succeeded"
    fake.rows = [_ok_row(KEYS[0]), bad]  # the third item is missing from the results
    rebuilt: list[str] = []

    def rebuild(key: str) -> dict[str, Any] | None:
        rebuilt.append(key)
        return _items([key])[0].inputs if key == KEYS[1] else None

    out = batch.collect(router, "extract_facts", rebuild_inputs=rebuild)
    by_key = {r.key: r for r in out.results}
    assert by_key[KEYS[0]].ok and not by_key[KEYS[0]].sync
    assert by_key[KEYS[1]].ok and by_key[KEYS[1]].sync and gemini.calls[0].model == "gemini-3.8-flash"
    assert not by_key[KEYS[2]].ok and "missing" in str(by_key[KEYS[2]].error)
    assert rebuilt == [KEYS[1], KEYS[2]]


def test_failed_batch_returns_its_items_to_the_queue(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini})
    job = batch.submit(router, "extract_facts", _items()).jobs[0]
    gemini.batches[job.provider_batch_id].state = "expired"
    out = batch.collect(router, "extract_facts")
    assert out.failed_keys == KEYS and out.results == []
    assert _batches()[0]["status"] == "expired"
    assert db.scalar("select bool_and(released) from public.llm_batch_reservations") is True
    assert store.items_in_flight("extract_facts", KEYS) == set()


def test_running_batch_stays_pending_and_is_marked_running(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini})
    job = batch.submit(router, "extract_facts", _items()).jobs[0]
    out = batch.collect(router, "extract_facts")
    assert out.pending == [job.llm_batch_id] and out.results == []
    assert _batches()[0]["status"] == "running"


def test_collect_polls_until_done_or_out_of_time(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini})
    job = batch.submit(router, "extract_facts", _items()).jobs[0]
    fake = gemini.batches[job.provider_batch_id]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake.state, fake.rows = "succeeded", [_ok_row(k) for k in KEYS]

    out = batch.collect(router, "extract_facts", max_wait_s=600, poll_s=60, sleep=sleep)
    assert sleeps == [60] and len(out.results) == 3 and out.pending == []


def test_cancel_open_cancels_and_releases(llm_db: str) -> None:
    gemini = FakeProvider("gemini")
    router = make_router({"gemini": gemini})
    job = batch.submit(router, "extract_facts", _items()).jobs[0]
    assert batch.cancel_open(router) == [job.llm_batch_id]
    assert gemini.cancelled == [job.provider_batch_id] and _batches()[0]["status"] == "cancelled"
    assert "submitted" in batch.describe(batch.SubmitResult())
