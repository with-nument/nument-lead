"""The golden set and the eval harness (Step 17.3 and 17.4): files, the fixed subset, every metric and
threshold, replay, the budget skip, the live pipeline with fakes, and export from the database."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from evals import golden, measures, run_eval
from evals.golden import Label, Truth
from evals.measures import MessageOutcome, Outcome, OutcomeFact
from evals.pipeline import EvalNotReady, LivePipeline, ReplayPipeline, clamp_grade, flatten, top_phone

from nument_engine import db
from nument_engine.models import FactsExtraction, LeadJudgement, MessageCheck, MessageDraft
from nument_engine.pipeline.runs import Options, RunContext, run_context

from .helpers import Conn


def bid(n: int) -> str:
    return str(uuid.UUID(int=n))


def label(n: int, segment: str = "clinics-in", lab: str = "good") -> Label:
    return Label(business_id=bid(n), segment=segment, label=lab, labeled_at=date(2026, 12, 1))


def write_labels(directory: Path, labels: list[Label]) -> None:
    (directory / "labels.jsonl").write_text("".join(x.model_dump_json() + "\n" for x in labels), encoding="utf-8")


TRUTH = Truth.model_validate(
    {
        "business_id": bid(1),
        "segment": "clinics-in",
        "checked_by": "builder",
        "checked_at": "2026-12-01",
        "facts": {
            "decision_maker": {"name": "Dr. Anika Deshmane", "role": "Founder"},
            "phones": [{"e164": "+919800054321", "type": "mobile"}],
            "branches_count": 12,
            "staff_count_min": 30,
            "booking_method": "phone and WhatsApp",
            "whatsapp_present": True,
            "chat_widget": False,
            "has_in_house_tech": "no",
            "is_agency_or_vendor": False,
            "services_include": ["ultrasound", "radiology"],
        },
    }
)


# ---------------------------------------------------------------------------
# Golden files
# ---------------------------------------------------------------------------


def test_labels_load_and_validate(tmp_path: Path) -> None:
    assert golden.load_labels(tmp_path) == []
    write_labels(tmp_path, [label(1), label(2, lab="bad")])
    assert [x.label for x in golden.load_labels(tmp_path)] == ["good", "bad"]
    (tmp_path / "labels.jsonl").write_text(label(1).model_dump_json() + "\n" + label(1).model_dump_json() + "\n")
    with pytest.raises(golden.GoldenError, match="labelled twice"):
        golden.load_labels(tmp_path)
    bad = json.loads(label(3).model_dump_json()) | {"reasons": ["vibes"]}
    (tmp_path / "labels.jsonl").write_text(json.dumps(bad) + "\n")
    with pytest.raises(golden.GoldenError, match="line 1"):
        golden.load_labels(tmp_path)


def test_truth_file_loads_and_rejects_unknown_keys(tmp_path: Path) -> None:
    doc = [json.loads(TRUTH.model_dump_json())]
    (tmp_path / "facts_truth.yaml").write_text(yaml.safe_dump(doc))
    assert golden.load_truth(tmp_path)[bid(1)].facts.branches_count == 12
    doc[0]["facts"]["favourite_colour"] = "indigo"
    (tmp_path / "facts_truth.yaml").write_text(yaml.safe_dump(doc))
    with pytest.raises(golden.GoldenError, match="entry 1"):
        golden.load_truth(tmp_path)


def test_ci_subset_is_stratified_balanced_and_fixed() -> None:
    labels, n = [], 0
    for seg, count in (
        ("clinics-in", 25),
        ("realestate-in", 15),
        ("education-in", 15),
        ("clinics-ae", 15),
        ("realestate-ae", 15),
        ("education-ae", 15),
    ):
        for i in range(count):
            n += 1
            labels.append(label(n, seg, "good" if i % 2 else "bad"))
    truth = {x.business_id for x in labels if int(x.business_id[-4:], 16) % 10 == 0}  # 10 hand-checked
    subset = golden.select_subset(labels, truth)
    by_id = {x.business_id: x for x in labels}
    assert len(subset) == 20 and len(set(subset)) == 20
    segs = Counter(by_id[i].segment for i in subset)
    assert segs["clinics-in"] >= 4 and all(segs[s] >= 3 for s in golden.WAVE1_QUOTA)
    assert Counter(by_id[i].label for i in subset) == {"good": 10, "bad": 10}
    assert sum(i in truth for i in subset) >= golden.SUBSET_MIN_TRUTH
    assert subset == golden.select_subset(labels, truth)


def test_subset_file_round_trip(tmp_path: Path) -> None:
    golden.write_subset([bid(1), bid(2)], tmp_path)
    assert golden.read_subset(tmp_path) == [bid(1), bid(2)]


# ---------------------------------------------------------------------------
# Comparing facts with the truth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("decision_maker", {"name": "Anika Deshmane", "role": "Director"}, True),
        ("decision_maker", {"name": "Dr. Someone Else"}, False),
        ("phone", {"number": "098000 54321"}, True),
        ("phone", {"number": "+91 99999 00000"}, False),
        ("branches", {"count": 12}, True),
        ("branches", {"count": 11}, False),
        ("staff_or_doctors", {"count": 34}, True),
        ("booking_method", {"value": "Call or WhatsApp us"}, True),
        ("booking_method", {"value": "Book online"}, False),
        ("whatsapp_present", {"value": True}, True),
        ("chat_widget", {"value": "Tidio live chat"}, False),
        ("in_house_tech", {"value": True}, False),
        ("is_agency_or_vendor", {"value": False}, True),
        ("service", {"name": "Ultrasound scans"}, True),
        ("service", {"name": "Dental implants"}, None),  # the truth list is partial
        ("email", {"email": "a@b.in"}, None),
    ],
)
def test_check_fact(field: str, value: dict[str, Any], expected: bool | None) -> None:
    assert measures.check_fact(OutcomeFact(field, value, True), TRUTH.facts, "in") is expected


def test_truth_items_skip_values_that_cannot_be_quoted() -> None:
    fields = [f for f, _ in measures.truth_items(TRUTH.facts)]
    assert fields.count("service") == 2 and "whatsapp_present" in fields
    assert "chat_widget" not in fields and "in_house_tech" not in fields and "is_agency_or_vendor" not in fields


# ---------------------------------------------------------------------------
# Metrics and thresholds
# ---------------------------------------------------------------------------


def outcomes_for(
    n_good: int, n_bad: int, *, good_grade: str = "A", bad_grade: str = "D"
) -> tuple[list[Outcome], dict[str, Label]]:
    outs, labels = [], {}
    for i in range(n_good + n_bad):
        good = i < n_good
        lab = label(100 + i, lab="good" if good else "bad")
        labels[lab.business_id] = lab
        msg = MessageOutcome(lint_ok_first=True, critic_score=9.0) if good else None
        outs.append(
            Outcome(lab.business_id, "clinics-in", total=90 - i, grade=good_grade if good else bad_grade, message=msg)
        )
    return outs, labels


def metric(report: measures.EvalReport, key: str) -> measures.MetricResult:
    return next(m for m in report.metrics if m.key == key)


def test_a_clean_run_passes_and_unmeasured_metrics_do_not_fail() -> None:
    outs, labels = outcomes_for(10, 10)
    report = measures.evaluate(outs, labels, {}, subset=True)
    assert report.passed
    assert metric(report, "grade_precision").value == 1.0 and metric(report, "grade_precision").label.endswith("at 10")
    assert metric(report, "bad_rejection").value == 1.0 and metric(report, "critic_score").value == 9.0
    assert metric(report, "fact_precision").passed is None  # no hand-checked business in this run
    assert "PASSED" in report.table()


def test_thresholds_differ_between_the_subset_and_the_full_set() -> None:
    outs, labels = outcomes_for(10, 10, bad_grade="B")
    for o in outs[13:]:
        o.grade = "C"  # 7 of 10 bad rejected = 70%
    assert metric(measures.evaluate(outs, labels, {}, subset=True), "bad_rejection").passed is True  # 60%
    assert metric(measures.evaluate(outs, labels, {}, subset=False), "bad_rejection").passed is True  # 70%
    outs[13].grade = "B"  # 60%
    assert metric(measures.evaluate(outs, labels, {}, subset=False), "bad_rejection").passed is False
    assert metric(measures.evaluate(outs, labels, {}, subset=True), "bad_rejection").passed is True


def test_messages_claims_and_errors_fail_the_gate() -> None:
    outs, labels = outcomes_for(10, 10)
    outs[0].message = MessageOutcome(lint_ok_first=False, critic_score=6.0, unverified_claims=1)
    report = measures.evaluate(outs, labels, {}, subset=True)
    assert metric(report, "lint_pass").value == 0.9 and metric(report, "lint_pass").passed is False
    assert metric(report, "unverified_claims").value == 1 and metric(report, "unverified_claims").passed is False
    assert not report.passed and "FAILED" in report.table()
    outs, labels = outcomes_for(10, 10)
    for o in outs[:3]:
        o.error = "boom"
    assert metric(measures.evaluate(outs, labels, {}, subset=True), "item_errors").passed is False


def test_fact_metrics_against_the_truth() -> None:
    lab = Label(business_id=bid(1), segment="clinics-in", label="good", labeled_at=date(2026, 12, 1))
    facts = [
        OutcomeFact("decision_maker", {"name": "Anika Deshmane"}, True),
        OutcomeFact("phone", {"number": "+91 98000 54321"}, True),
        OutcomeFact("branches", {"count": 10}, True),  # wrong
        OutcomeFact("service", {"name": "Radiology"}, True),
        OutcomeFact("whatsapp_present", {"value": True}, False),  # not verified: ignored
    ]
    out = Outcome(
        bid(1),
        "clinics-in",
        total=80,
        grade="A",
        facts=facts,
        top_phone_e164="+919800054321",
        message=MessageOutcome(True, 9.0),
    )
    report = measures.evaluate([out], {lab.business_id: lab}, {bid(1): TRUTH}, subset=True)
    assert metric(report, "fact_precision").value == pytest.approx(3 / 4)
    assert metric(report, "field_recall").value == pytest.approx(3 / 8)  # name, phone, radiology of 8 items
    assert metric(report, "phone_accuracy").value == 1.0


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------


def rc(**opts: Any) -> RunContext:
    return RunContext("00000000-0000-0000-0000-000000000000", "manual", Options(**opts), datetime.now(UTC))


def test_no_golden_set_means_not_ready(tmp_path: Path) -> None:
    with pytest.raises(EvalNotReady, match="no labels yet"):
        run_eval.run(rc(), golden_dir=tmp_path)


def test_dry_run_shows_the_selection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_labels(tmp_path, [label(1), label(2, lab="bad")])
    assert run_eval.run(rc(dry_run=True), golden_dir=tmp_path)["status"] == "dry_run"
    assert "2 businesses (1 good, 1 bad)" in capsys.readouterr().out


def test_replay_stores_an_eval_report(engine_db: str, tmp_path: Path) -> None:
    outs, labels = outcomes_for(10, 10)
    write_labels(tmp_path, list(labels.values()))
    replay = tmp_path / "outcomes.jsonl"
    replay.write_text("".join(json.dumps(o.as_dict()) + "\n" for o in outs))
    with run_context("manual", Options()) as ctx:
        result = run_eval.run(ctx, subset=20, replay=replay, golden_dir=tmp_path)
    assert result["status"] == "passed" and result["report_id"]
    row = db.fetch_one("select kind, content, markdown from public.reports where id = %s", [result["report_id"]])
    assert row is not None and row["kind"] == "eval" and row["content"]["summary"]["passed"] is True
    assert row["markdown"].startswith("# Eval: passed on 20 businesses")
    assert ReplayPipeline(replay).run(label(999)).error == "not in replay file"
    db.execute("delete from public.reports where id = %s", [result["report_id"]])


def test_budget_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_labels(tmp_path, [label(1)])
    monkeypatch.setattr(run_eval, "budget_check", lambda n: (False, "today's spend passes the cap"))
    result = run_eval.run(rc(), golden_dir=tmp_path)
    assert result == {"status": "skipped_budget", "passed": False, "detail": "today's spend passes the cap"}


# ---------------------------------------------------------------------------
# The live pipeline with fake stages
# ---------------------------------------------------------------------------


def test_flatten_and_top_phone() -> None:
    extraction = FactsExtraction.model_validate(
        {
            "phones": [
                {"number": "020 2553 1234", "belongs_to": "business", "quote": "Call 020 2553 1234", "url": "u"},
                {"number": "98200 12345", "belongs_to": "person", "quote": "Dr. Rao 98200 12345", "url": "u"},
            ],
            "branches": {"count": 3, "quote": "three branches", "url": "u"},
        }
    )
    rows = flatten(extraction)
    assert [r["field"] for r in rows] == ["phone", "phone", "branches"] and rows[2]["value"] == {"count": 3}
    for r in rows:
        r["verified"] = True
    assert top_phone(rows, "in") == ("+919820012345", "mobile")
    assert clamp_grade("B", "D") == "C" and clamp_grade("A", "A") == "A" and clamp_grade("D", "A") == "C"


def test_live_pipeline_runs_production_stages_on_frozen_pages(tmp_path: Path) -> None:
    lab = label(7)
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    page = {"url": "https://c.example.com/", "text": "Dr. Asha Rao runs three branches. Call 98200 12345 to book."}
    (pages_dir / f"{lab.business_id}.json").write_text(json.dumps({"pages": [page]}))
    calls: list[str] = []

    def run_task(task: str, inputs: dict[str, Any], *, lead_id: str | None = None) -> Any:
        calls.append(task)
        if task == "extract_facts":
            assert inputs["pages"] == [page]
            return FactsExtraction.model_validate(
                {
                    "decision_makers": [
                        {
                            "name": "Dr. Asha Rao",
                            "is_decision_maker": True,
                            "quote": "Dr. Asha Rao runs",
                            "url": page["url"],
                        }
                    ],
                    "phones": [
                        {
                            "number": "98200 12345",
                            "belongs_to": "business",
                            "quote": "Call 98200 12345",
                            "url": page["url"],
                        }
                    ],
                    "branches": {"count": 3, "quote": "made up quote here", "url": page["url"]},
                }
            )
        if task == "judge_lead":
            return LeadJudgement(
                judge_grade="A", cited_ids=["F1"], judge_note="Busy clinic.", best_angle="missed_calls", confidence=0.8
            )
        if task == "write_message":
            return MessageDraft(
                message="Hi Dr. Rao, saw your three branches.",
                message_alt="Hi",
                followup_d3="x",
                followup_d7="y",
                claims=[{"text": "three branches", "ids": ["F9"]}],
            )
        return MessageCheck(score=9)

    def score_business(
        b: dict[str, Any], facts: list[dict[str, Any]], signals: list[Any], contacts: list[Any], seg: Any
    ) -> Any:
        assert [f["field"] for f in facts] == ["decision_maker", "phone"] and contacts[0]["phone_type"] == "mobile"
        return SimpleNamespace(
            total=64,
            grade="B",
            fit=3,
            can_pay=20,
            intent=8,
            reach=0.85,
            pitch_mode="visible_pain",
            angle="missed_calls",
        )

    pipeline = LivePipeline(
        run_task=run_task,
        still_there=lambda q, t: q.lower() in t.lower(),
        score_business=score_business,
        lint=lambda text, kind: [],
        golden_dir=tmp_path,
        business_row=lambda b: None,
        signals_of=lambda b: [],
    )
    out = pipeline.run(lab)
    assert calls == ["extract_facts", "judge_lead", "write_message", "check_message"]
    assert (out.total, out.grade, out.top_phone_e164) == (64, "A", "+919820012345")  # judge moved B to A
    assert [f.verified for f in out.facts] == [True, True, False]
    assert out.message == MessageOutcome(lint_ok_first=True, critic_score=9.0, unverified_claims=1)
    missing = pipeline.run(label(8))
    assert missing.error and "no frozen pages" in missing.error


# ---------------------------------------------------------------------------
# Export from the database
# ---------------------------------------------------------------------------


def test_export_golden_writes_labels_pages_and_subset(db_conn: Conn, tmp_path: Path) -> None:
    from . import seed

    biz = seed.business(db_conn, "clinics-ae")
    db_conn.execute(
        "insert into public.golden_labels (business_id, label, reasons) values (%s, 'bad', %s)",
        [biz, json.dumps(["agency_or_vendor"])],
    )
    db_conn.execute(
        "insert into public.pages (business_id, url, text, text_hash) values (%s, %s, 'We build apps for clinics', 'h1')",
        [biz, f"https://{uuid.uuid4().hex[:8]}.example.com/"],
    )
    counts = golden.export_golden(tmp_path, conn=db_conn)
    assert counts["labels"] >= 1 and counts["frozen_pages"] >= 1
    exported = {x.business_id: x for x in golden.load_labels(tmp_path)}
    assert exported[biz].label == "bad" and exported[biz].reasons == ["agency_or_vendor"]
    assert golden.load_pages(biz, tmp_path)[0]["text"] == "We build apps for clinics"
    assert golden.read_subset(tmp_path)
