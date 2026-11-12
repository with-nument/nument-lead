"""Rule pre-filter and research queue (Step 8): every rule code, the priority formula, quotas and the run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.pipeline import prefilter
from nument_engine.pipeline.prefilter import Exclusions, Item, World, apply_rules, build_queue, priority, segment_slots

from .sources_helpers import clean_db, insert_business, no_network, run_context, segment

__all__ = ["clean_db", "no_network"]

SEG = segment()
NOW = datetime(2026, 11, 12, 2, 0, tzinfo=UTC)
EXCL = Exclusions.load()


def biz(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "b1",
        "segment_id": "clinics-in",
        "name": "Lotus Skin Clinic",
        "norm_name": "lotus skin clinic",
        "website": "https://lotusskin-nlead.in/",
        "web_domain": "lotusskin-nlead.in",
        "city": "Pune",
        "category": "dermatology",
        "subcategory": "dermatology",
        "branches_count": None,
        "review_count": 150,
        "places_fetched_at": NOW - timedelta(days=3),
        "status": "candidate",
        "researched_at": None,
        "queued_at": None,
        "extra": {},
    }
    base.update(kw)
    if "name" in kw and "norm_name" not in kw:
        from nument_engine.normalize import norm_name

        base["norm_name"] = norm_name(kw["name"])
    return base


def signal(
    kind: str = "hiring_frontdesk",
    category: str = "visible_pain",
    age_days: float = 2,
    points: float = 8,
    window: int = 30,
    created: datetime | None = None,
) -> dict[str, Any]:
    observed = NOW - timedelta(days=age_days)
    return {
        "type": kind,
        "category": category,
        "points": points,
        "observed_at": observed,
        "expires_at": observed + timedelta(days=window),
        "created_at": created or observed,
    }


def world(**kw: Any) -> World:
    w = World()
    for key, value in kw.items():
        if isinstance(getattr(w, key), dict):
            getattr(w, key).update(value)
        else:
            setattr(w, key, value)
    return w


@pytest.mark.parametrize(
    ("b", "w", "expected"),
    [
        (biz(), world(), ("pass", None)),
        (biz(city="Lucknow"), world(), ("skip", "R1_segment")),
        (biz(category="hospital", subcategory=None), world(), ("reject", "R2_category")),
        (biz(category=None, subcategory=None), world(), ("skip", "R2_category_unknown")),
        (biz(category=None, subcategory=None), world(signals={"b1": [signal()]}), ("pass", None)),
        (biz(web_domain="clovedental.in"), world(), ("reject", "R3_excluded")),
        (biz(name="Fortis Skin Centre"), world(), ("reject", "R3_excluded")),
        (biz(name="Sunrise Multispeciality Hospital"), world(), ("reject", "R3_excluded")),
        (biz(branches_count=12), world(), ("reject", "R3_excluded")),
        (biz(name="DLF Phase 4 Skin Clinic"), world(), ("pass", None)),  # a locality, not the DLF chain
        (biz(name="Pixel Digital Marketing Agency"), world(), ("reject", "R4_agency")),
        (biz(), world(suppressed_domains={"lotusskin-nlead.in"}), ("suppress", "R5_suppressed")),
        (
            biz(),
            world(phones={"b1": {"+919800000001"}}, suppressed_phones={"+919800000001"}),
            ("suppress", "R5_suppressed"),
        ),
        (biz(), world(open_lead={"b1"}), ("skip", "R6_open_lead")),
        (biz(), world(last_closed={"b1": NOW - timedelta(days=10)}), ("skip", "R7_cooldown")),
        (
            biz(),
            world(
                last_closed={"b1": NOW - timedelta(days=10)},
                signals={"b1": [signal("public_ask", "stated_need", created=NOW - timedelta(days=1))]},
            ),
            ("pass", None),
        ),
        (biz(researched_at=NOW - timedelta(days=20)), world(), ("skip", "R8_recent")),
        (biz(researched_at=NOW - timedelta(days=20)), world(signals={"b1": [signal(created=NOW)]}), ("pass", None)),
        (biz(review_count=20), world(), ("skip", "R9_size")),
        (biz(review_count=500, places_fetched_at=NOW - timedelta(days=40)), world(), ("skip", "R9_size")),  # stale
        (biz(review_count=None), world(record_sources={"b1": {"art_registry"}}), ("pass", None)),
        (biz(review_count=None), world(), ("pass", None)),  # no review data, own website: research measures size
        (biz(review_count=None, website=None, web_domain=None), world(emails={"b1": {"a@x.in"}}), ("skip", "R9_size")),
        (biz(review_count=None), world(facts={"b1": {"staff_or_doctors": {"count": 3}}}), ("pass", None)),
        (biz(review_count=None), world(signals={"b1": [signal("public_ask", "stated_need")]}), ("pass", None)),
        (biz(website=None, web_domain=None), world(), ("reject", "no_contact_route")),
        (biz(website=None, web_domain=None), world(emails={"b1": {"care@x.in"}}), ("pass", None)),
        (
            biz(website=None, web_domain=None, extra={"born_from": "apna"}),
            world(signals={"b1": [signal()]}),
            ("skip", "R10_waiting_lookup"),
        ),
        (biz(status="dormant"), world(), ("skip", "R11_dormant")),
    ],
)
def test_rules(b: dict[str, Any], w: World, expected: tuple[str, str | None]) -> None:
    assert apply_rules(b, SEG, EXCL, w, NOW) == expected


def test_priority_formula() -> None:
    fresh_ask = priority(
        biz(review_count=99, branches_count=2), [signal("public_ask", "stated_need", 1, 10, 14)], 0, NOW
    )
    # 100 x 1.0 x 1.0 + 15 + min(20, 6 x log10(100) + 4 x 1) = 115 + 16
    assert fresh_ask.priority == pytest.approx(131.0) and not fresh_ask.fit_only
    old_pain = priority(biz(review_count=0), [signal(age_days=20)], 0, NOW)  # 20 of 30 days: freshness 0.4
    assert old_pain.priority == pytest.approx(100 * 0.8 * 0.4 + 8)
    fit = priority(biz(review_count=999, branches_count=5), [], 3.0, NOW)
    assert fit.fit_only and fit.priority == pytest.approx(20 + 3.0)


def item(seg: str, n: int, prio: float, fit: bool = False) -> Item:
    return Item(f"{seg}-{n}", seg, prio, fit, None if fit else "visible_pain", NOW, 0)


def test_queue_respects_quotas_fit_only_cap_and_fills_spare_slots() -> None:
    passed = [item("clinics-in", i, 100 - i) for i in range(50)]
    passed += [item("education-in", i, 50 - i) for i in range(5)]
    passed += [item("clinics-in", 100 + i, 90, fit=True) for i in range(20)]
    queue = build_queue(passed, slots=40, quotas={"clinics-in": 20, "education-in": 20})
    assert len(queue) == 40
    assert sum(i.fit_only for i in queue) <= 4  # 10% of slots
    assert sum(i.segment_id == "education-in" for i in queue) == 5  # all it has
    assert sum(i.segment_id == "clinics-in" for i in queue) == 35  # its quota plus the slots education left


def test_segment_shares_scale_down_with_a_10_percent_floor() -> None:
    quotas = {
        "clinics-in": 80,
        "realestate-in": 60,
        "education-in": 50,
        "clinics-ae": 40,
        "realestate-ae": 40,
        "education-ae": 30,
    }
    shares = segment_slots(100, quotas, set(quotas))
    assert sum(shares.values()) <= 100 and all(v >= 10 for v in shares.values())
    assert segment_slots(400, quotas, set(quotas)) == quotas
    assert segment_slots(100, {**quotas, "education-ae": 0}, set(quotas)).get("education-ae") is None


def test_the_stage_rejects_queues_and_does_not_grow_on_a_rerun(clean_db: str) -> None:
    good = insert_business(
        name="Queue Test Skin Clinic",
        website="https://queuetest-nlead.in/",
        web_domain="queuetest-nlead.in",
        category="dermatology",
        subcategory="dermatology",
        review_count=200,
        places_fetched_at=datetime.now(UTC),
    )
    chain = insert_business(
        name="Fortis Skin Clinic Queue Test",
        category="dermatology",
        subcategory="dermatology",
        review_count=500,
        places_fetched_at=datetime.now(UTC),
        website="https://x-nlead.in/",
    )
    db.execute("update public.segments set daily_quota = 300 where id = 'clinics-in'")
    rc = run_context(segments=["clinics-in"])
    stats = prefilter.run(rc)
    rows = {
        r["id"]: r
        for r in db.fetch_all(
            "select id::text, status, reject_reason, queue_priority from public.businesses where id = any(%s)",
            [[good, chain]],
        )
    }
    assert rows[good]["status"] == "queued" and rows[good]["queue_priority"] is not None
    assert rows[chain]["status"] == "rejected" and rows[chain]["reject_reason"] == "R3_excluded"
    assert stats["queued"] >= 1 and rc.stats["prefilter"] is stats
    again = prefilter.run(run_context(segments=["clinics-in"]))
    assert again["queued"] == 0  # already queued today: the queue does not grow


def test_money_check_limits_the_queue(clean_db: str) -> None:
    db.set_setting("daily_cap_inr", 1)  # about nothing left today
    slots, _, why = prefilter.today_slots(["clinics-in"])
    assert slots == 0 and why["money_slots"] == 0


def test_dry_run_changes_nothing(clean_db: str) -> None:
    bid = insert_business(
        name="Dry Prefilter Clinic",
        website="https://dryprefilter-nlead.in/",
        web_domain="dryprefilter-nlead.in",
        category="dermatology",
        subcategory="dermatology",
        review_count=200,
        places_fetched_at=datetime.now(UTC),
    )
    prefilter.run(run_context(segments=["clinics-in"], dry_run=True))
    assert db.scalar("select status from public.businesses where id = %s", [bid]) == "candidate"


def test_the_fit_only_share_can_be_raised_by_setting() -> None:
    passed = [item("clinics-in", 100 + i, 90, fit=True) for i in range(30)]
    assert sum(i.fit_only for i in build_queue(passed, slots=20, quotas={"clinics-in": 20})) == 2  # default 10%
    raised = build_queue(passed, slots=20, quotas={"clinics-in": 20}, fit_only_share=0.5)
    assert sum(i.fit_only for i in raised) == 10
    assert len(build_queue(passed, slots=20, quotas={"clinics-in": 20}, fit_only_share=7)) == 20  # clamped to 100%
