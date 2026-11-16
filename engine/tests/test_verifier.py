"""Email checks without sending (lane E3): provider answers, switching, caps, the cache and the re-check phase.

Every HTTP answer comes from `httpx.MockTransport` with the documented sample responses in fixtures/e3; no
request leaves the machine (the respx guard fails any request without a mock)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.budget import ist_today
from nument_engine.outreach import verifier as v
from nument_engine.pipeline.runs import Options, RunContext

from .sources_helpers import clean_db, no_network

__all__ = ["clean_db", "no_network"]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e3"
QEV_KEY = "qev-test-key"
MEV_KEY = "mev-test-key"
QEV_HOST = "api.quickemailverification.com"
MEV_HOST = "client.myemailverifier.com"


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------------------------------
# Mapping the providers' answers
# ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "result", "catch_all"),
    [
        ("qev_safe_to_send.json", "deliverable", False),
        ("qev_accept_all.json", "risky", True),
        ("qev_rejected_email.json", "undeliverable", False),
        ("qev_timeout.json", "unknown", None),
        ("qev_role.json", "risky", False),
    ],
)
def test_quickemailverification_answers(name: str, result: str, catch_all: bool | None) -> None:
    got, flag, kept = v.parse_qev(200, fixture(name))
    assert (got, flag) == (result, catch_all)
    assert "email" not in kept and "user" not in kept and "did_you_mean" not in kept  # minimal data only


def test_a_valid_answer_without_every_safety_flag_is_never_deliverable() -> None:
    base = fixture("qev_safe_to_send.json")
    for change in ({"accept_all": None}, {"safe_to_send": "false"}, {"disposable": "true"}, {"accept_all": "maybe"}):
        body = {k: val for k, val in {**base, **change}.items() if val is not None}
        assert v.parse_qev(200, body)[0] == "risky", change
    assert v.parse_qev(200, {**base, "disposable": None})[0] == "risky"  # a missing flag is not a clean one


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (402, fixture("qev_low_credit.json"), "quota"),
        (200, fixture("qev_low_credit.json"), "quota"),
        (200, fixture("qev_ip_not_allowed.json"), "auth"),
        (401, {}, "auth"),
        (403, None, "auth"),
        (429, None, "rate_limited"),
        (500, None, "transient"),
        (503, {"oops": True}, "transient"),
        (404, None, "malformed"),
        (200, None, "malformed"),
        (200, ["not", "an", "object"], "malformed"),
        (200, {**fixture("qev_safe_to_send.json"), "result": "excellent"}, "malformed"),
        (200, {"success": "false", "message": "something else"}, "malformed"),
    ],
)
def test_quickemailverification_errors(status: int, body: Any, kind: str) -> None:
    with pytest.raises(v.VerifierError) as err:
        v.parse_qev(status, body)
    assert err.value.kind == kind and err.value.provider == v.QEV


@pytest.mark.parametrize(
    ("name", "result", "catch_all"),
    [
        ("mev_valid.json", "deliverable", False),
        ("mev_invalid.json", "undeliverable", None),
        ("mev_catch_all.json", "risky", True),
        ("mev_unknown.json", "unknown", False),
    ],
)
def test_myemailverifier_answers(name: str, result: str, catch_all: bool | None) -> None:
    got, flag, kept = v.parse_mev(200, fixture(name))
    assert (got, flag) == (result, catch_all)
    assert "Address" not in kept and kept["Diagnosis"]


def test_myemailverifier_risky_answers() -> None:
    valid = fixture("mev_valid.json")
    assert v.parse_mev(200, {**valid, "Role_Based": "true"})[0] == "risky"
    assert v.parse_mev(200, {**valid, "Disposable_Domain": "true"})[0] == "risky"
    assert v.parse_mev(200, {k: val for k, val in valid.items() if k != "catch_all"})[0] == "risky"
    assert v.parse_mev(200, {**valid, "Greylisted": "true"})[0] == "unknown"
    assert v.parse_mev(200, {**valid, "Status": "Catch All", "catch_all": "false"})[:2] == ("risky", True)
    assert v.parse_mev(200, {**valid, "Status": "Spamtrap"})[0] == "undeliverable"


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (429, fixture("mev_rate_limited.json"), "rate_limited"),
        (200, fixture("mev_rate_limited.json"), "rate_limited"),
        (200, fixture("mev_insufficient_credits.json"), "quota"),
        (402, None, "quota"),
        (401, fixture("mev_invalid_key.json"), "auth"),
        (403, {"status": False, "error": "UNAUTHORIZED_REFERER"}, "auth"),
        (500, {"status": False, "error": "SERVER_ERROR"}, "transient"),
        (400, {"status": False, "error": "INVALID_REQUEST"}, "malformed"),
        (200, "<html>maintenance</html>", "malformed"),
        (200, {"status": False, "msg": "Something went wrong"}, "malformed"),
        (200, {**fixture("mev_valid.json"), "Status": "Excellent"}, "malformed"),
    ],
)
def test_myemailverifier_errors(status: int, body: Any, kind: str) -> None:
    with pytest.raises(v.VerifierError) as err:
        v.parse_mev(status, body)
    assert err.value.kind == kind and err.value.provider == v.MEV


def check(result: str, catch_all: bool | None) -> v.Check:
    return v.Check("maya@brightcart.io", result, catch_all, v.QEV, {}, datetime.now(UTC))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current", "origin", "answer", "expected"),
    [
        ("likely", "guess", check("deliverable", False), "verified"),
        ("verified", "published", check("undeliverable", None), "invalid"),
        ("verified", "guess", check("risky", True), "unknown"),  # a guess on a catch-all domain is unproven
        ("likely", "guess", check("risky", True), "likely"),  # its pattern was backed by a published address
        ("verified", "guess", check("unknown", None), "unknown"),
        ("verified", "published", check("unknown", None), "likely"),
        ("verified", "archive", check("risky", True), "likely"),
        ("unknown", "snippet", check("risky", False), "unknown"),  # an unconfirmed snippet is not published
        ("likely", "post", check("deliverable", False), "verified"),
    ],
)
def test_relabel_after_a_recheck(current: str, origin: str, answer: v.Check, expected: str) -> None:
    assert v.relabel(current, origin, answer) == expected


def test_a_provider_never_shows_its_key() -> None:
    assert QEV_KEY not in repr(v.QuickEmailVerification(QEV_KEY))
    assert MEV_KEY not in repr(v.MyEmailVerifier(MEV_KEY))


# ---------------------------------------------------------------------------------------------------
# The verifier against the test database
# ---------------------------------------------------------------------------------------------------


@pytest.fixture
def e3_db(clean_db: str) -> Iterator[str]:
    """E3 tests own email_checks and email_domains: both start and end empty."""
    db.execute("delete from public.email_checks")
    db.execute("delete from public.email_domains")
    try:
        yield clean_db
    finally:
        db.execute("delete from public.email_checks")
        db.execute("delete from public.email_domains")


Handler = Callable[[httpx.Request], httpx.Response]


class Api:
    """A fake for both providers: one handler per host, every request recorded."""

    def __init__(self, qev: Handler | None = None, mev: Handler | None = None) -> None:
        self.handlers = {QEV_HOST: qev, MEV_HOST: mev}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.handlers.get(request.url.host)
        if handler is None:
            raise AssertionError(f"unexpected request to {request.url.host}")
        return handler(request)

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


def answer(status: int, name: str | None = None, body: Any = None) -> Handler:
    payload = fixture(name) if name else body
    if isinstance(payload, str):
        return lambda request: httpx.Response(status, text=payload)
    return lambda request: httpx.Response(status, json=payload)


def raises(exc: type[httpx.HTTPError]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc("boom", request=request)

    return handler


def make(api: Api, *, providers: tuple[str, ...] = (v.QEV, v.MEV)) -> v.Verifier:
    chosen: list[v.Provider] = []
    for name in providers:
        chosen.append(v.QuickEmailVerification(QEV_KEY) if name == v.QEV else v.MyEmailVerifier(MEV_KEY))
    return v.Verifier(chosen, transport=httpx.MockTransport(api))


def test_a_live_check_is_stored_without_the_key_and_reused(e3_db: str) -> None:
    api = Api(qev=answer(200, "qev_safe_to_send.json"))
    with make(api) as checker:
        first = checker.check("Maya@Brightcart.io")
        again = checker.check("maya@brightcart.io")
    assert first is not None and first.result == "deliverable" and first.deliverable and not first.cached
    assert again is not None and again.cached and again.deliverable
    assert len(api.requests) == 1  # the second answer came from the cache
    sent = api.requests[0]
    assert sent.url.params["email"] == "maya@brightcart.io" and sent.url.params["apikey"] == QEV_KEY
    row = db.fetch_one("select * from public.email_checks where email = 'maya@brightcart.io'")
    assert row is not None and row["result"] == "deliverable" and row["provider"] == v.QEV
    assert QEV_KEY not in json.dumps(row["raw"], default=str) and "http" not in json.dumps(row["raw"])
    domain = db.fetch_one("select * from public.email_domains where domain = 'brightcart.io'")
    assert domain is not None and domain["catch_all"] is False


def test_myemailverifier_puts_the_key_in_the_path(e3_db: str) -> None:
    api = Api(mev=answer(200, "mev_catch_all.json"))
    with make(api, providers=(v.MEV,)) as checker:
        got = checker.check("maya@brightcart.io")
    assert got is not None and (got.result, got.catch_all) == ("risky", True)
    assert api.requests[0].url.path == f"/verifier/validate_single/maya@brightcart.io/{MEV_KEY}"
    assert db.scalar("select catch_all from public.email_domains where domain = 'brightcart.io'") is True


def test_the_cache_keeps_answers_30_days_but_unknown_only_one(e3_db: str) -> None:
    now = datetime.now(UTC)
    rows = [
        ("old@brightcart.io", "deliverable", now - timedelta(days=31)),
        ("recent@brightcart.io", "undeliverable", now - timedelta(days=10)),
        ("vague@brightcart.io", "unknown", now - timedelta(hours=30)),
        ("vague-today@brightcart.io", "unknown", now - timedelta(hours=2)),
    ]
    for email, result, at in rows:
        db.execute(
            "insert into public.email_checks (email, result, provider, raw, checked_at) values (%s, %s, %s, %s, %s)",
            [email, result, v.QEV, db.Jsonb({"catch_all": None, "fields": {}}), at],
        )
    checker = make(Api())
    assert checker.cached("old@brightcart.io") is None
    recent = checker.cached("recent@brightcart.io")
    assert recent is not None and recent.result == "undeliverable" and recent.cached
    assert checker.cached("vague@brightcart.io") is None
    assert checker.cached("vague-today@brightcart.io") is not None


def test_429_switches_to_the_backup_for_the_rest_of_the_run(e3_db: str) -> None:
    api = Api(qev=answer(429, body={"success": "false"}), mev=answer(200, "mev_valid.json"))
    with make(api) as checker:
        first = checker.check("maya@brightcart.io")
        second = checker.check("leo@brightcart.io")
    assert first is not None and first.provider == v.MEV and first.deliverable
    assert second is not None and second.provider == v.MEV
    assert api.hosts() == [QEV_HOST, MEV_HOST, MEV_HOST]  # QuickEmailVerification is not asked again
    assert checker.off == {v.QEV: "rate_limited"}


def test_a_spent_quota_is_remembered_for_the_day(e3_db: str) -> None:
    api = Api(qev=answer(402, "qev_low_credit.json"), mev=answer(200, "mev_invalid.json"))
    with make(api) as checker:
        got = checker.check("maya@brightcart.io")
    assert got is not None and got.result == "undeliverable" and got.provider == v.MEV
    assert db.get_setting(f"email_check.exhausted.{v.QEV}") == ist_today().isoformat()
    later = Api(qev=answer(200, "qev_safe_to_send.json"), mev=answer(200, "mev_valid.json"))
    with make(later) as checker:
        assert checker.check("leo@brightcart.io") is not None
    assert later.hosts() == [MEV_HOST]  # a new run the same day goes straight to the backup


def test_a_refused_key_and_failures_switch_providers(e3_db: str) -> None:
    api = Api(qev=answer(401, body={"success": "false", "message": "bad key"}), mev=answer(200, "mev_valid.json"))
    with make(api) as checker:
        assert checker.check("maya@brightcart.io") is not None
    assert checker.off == {v.QEV: "auth"}

    flaky = Api(qev=raises(httpx.ConnectTimeout), mev=answer(200, "mev_valid.json"))
    with make(flaky) as checker:
        for n in range(4):
            got = checker.check(f"person{n}@brightcart.io")
            assert got is not None and got.provider == v.MEV
    assert flaky.hosts().count(QEV_HOST) == v.MAX_TRANSIENT  # left alone after three failures in a row
    assert checker.off[v.QEV] == "failing"


def test_bad_json_moves_on_and_both_down_means_no_answer(e3_db: str) -> None:
    api = Api(qev=answer(200, body="<html>gateway</html>"), mev=answer(200, "mev_valid.json"))
    with make(api) as checker:
        got = checker.check("maya@brightcart.io")
    assert got is not None and got.provider == v.MEV
    assert checker.stats[f"{v.QEV}.malformed"] == 1

    down = Api(qev=answer(402, "qev_low_credit.json"), mev=answer(200, "mev_insufficient_credits.json"))
    with make(down) as checker:
        assert checker.check("leo@brightcart.io") is None
        assert checker.check("ana@brightcart.io") is None
        assert not checker.available()
    assert len(down.requests) == 2  # both providers answered "no credits" once, then nobody was asked
    assert checker.stats["no_provider"] == 2
    errors = "select count(*) from public.email_checks where email in ('leo@brightcart.io', 'ana@brightcart.io')"
    assert db.scalar(errors) == 0  # an error is never cached


def test_daily_caps_across_and_per_provider(e3_db: str) -> None:
    db.set_setting("email_check.per_day", 2)
    api = Api(qev=answer(200, "qev_safe_to_send.json"), mev=answer(200, "mev_valid.json"))
    with make(api) as checker:
        assert checker.check("a@brightcart.io") is not None
        assert checker.check("b@brightcart.io", reserve=1) is None  # one check kept for later
        assert checker.check("b@brightcart.io") is not None
        assert checker.check("c@brightcart.io") is None
    assert len(api.requests) == 2 and checker.stats["capped"] == 2

    db.set_setting("email_check.per_day", 150)
    db.set_setting("email_check.qev_per_day", 2)
    with make(api) as checker:
        got = checker.check("d@brightcart.io")
    assert got is not None and got.provider == v.MEV and checker.off == {v.QEV: "daily_cap"}


def test_without_keys_nothing_is_checked(e3_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    checker = v.Verifier.from_settings()
    assert not checker.configured and checker.check("maya@brightcart.io") is None
    monkeypatch.setenv("QEV_API_KEY", QEV_KEY)
    from nument_engine.settings import get_settings

    get_settings.cache_clear()
    configured = v.Verifier.from_settings()
    assert [p.name for p in configured.providers] == [v.QEV]


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))

    info = warning = error = _record


def test_no_key_or_url_reaches_a_log_line_or_an_error(e3_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()
    monkeypatch.setattr(v, "log", recorder)
    api = Api(qev=raises(httpx.ConnectError), mev=answer(429, "mev_rate_limited.json"))
    with make(api) as checker:
        assert checker.check("maya@brightcart.io") is None
    text = json.dumps(recorder.events, default=str) + json.dumps(dict(checker.stats))
    assert QEV_KEY not in text and MEV_KEY not in text and "https://" not in text
    with pytest.raises(v.VerifierError) as err, make(Api(mev=raises(httpx.ReadTimeout)), providers=(v.MEV,)) as c:
        c._ask(c.providers[0], "maya@brightcart.io")
    assert err.value.__cause__ is None and err.value.__suppress_context__  # the httpx error (and URL) is dropped
    assert MEV_KEY not in str(err.value)


# ---------------------------------------------------------------------------------------------------
# verify_emails: the re-check before sending (outreach run)
# ---------------------------------------------------------------------------------------------------


def rc() -> RunContext:
    return RunContext(run_id=str(uuid.uuid4()), kind="manual", opts=Options(), started_at=datetime.now(UTC))


def thread_for(email: str, *, status: str, checked_days_ago: float | None, scheduled_in_days: float | None) -> str:
    """A business, a lead, a founder contact with `email`, an open thread and a step 0 draft. Returns the
    contact id."""
    tag = uuid.uuid4().hex[:8]
    with db.tx() as conn:
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, country, city, web_domain) "
            "values ('clinics-in', %s, %s, 'in', 'Pune', %s) returning id",
            [f"Brightcart {tag}", f"brightcart {tag}", f"brightcart-{tag}.io"],
        ).fetchone()
        assert biz is not None
        checked = datetime.now(UTC) - timedelta(days=checked_days_ago) if checked_days_ago is not None else None
        contact = conn.execute(
            "insert into public.contacts (business_id, name, role, email, source, line, is_decision_maker, "
            "email_status, email_origin, email_pattern, email_checked_at) "
            "values (%s, 'Maya Chen', 'Founder', %s, 'website', 'owner', true, %s, 'guess', 'first', %s) "
            "returning id",
            [biz["id"], email, status, checked],
        ).fetchone()
        assert contact is not None
        lead = conn.execute(
            "insert into public.leads (business_id, segment_id, grade, pitch_mode, channel) "
            "values (%s, 'clinics-in', 'A', 'fit_only', 'email') returning id",
            [biz["id"]],
        ).fetchone()
        assert lead is not None
        thread = conn.execute(
            "insert into public.email_threads (lead_id, contact_id, to_email, to_domain) values (%s, %s, %s, %s) "
            "returning id",
            [lead["id"], contact["id"], email, email.split("@")[1]],
        ).fetchone()
        assert thread is not None
        due = datetime.now(UTC) + timedelta(days=scheduled_in_days) if scheduled_in_days is not None else None
        conn.execute(
            "insert into public.email_messages (thread_id, direction, step, subject, body, status, scheduled_for) "
            "values (%s, 'out', 0, 'Hello', 'Hi Maya', 'draft', %s)",
            [thread["id"], due],
        )
    return str(contact["id"])


def contact_row(contact_id: str) -> dict[str, Any]:
    row = db.fetch_one("select email_status, email_checked_at from public.contacts where id = %s", [contact_id])
    assert row is not None
    return row


def test_recheck_does_nothing_while_outreach_is_off(e3_db: str) -> None:
    assert v.run(rc(), verifier=make(Api())) == {"skipped": "outreach off"}


def test_recheck_before_sending(e3_db: str) -> None:
    db.set_setting("outreach.mode", "manual")
    stale = thread_for("maya@stale-co.io", status="verified", checked_days_ago=40, scheduled_in_days=None)
    never = thread_for("leo@never-co.io", status="likely", checked_days_ago=None, scheduled_in_days=0.5)
    fresh = thread_for("ana@fresh-co.io", status="verified", checked_days_ago=5, scheduled_in_days=None)
    later = thread_for("raj@later-co.io", status="verified", checked_days_ago=40, scheduled_in_days=3)
    vague = thread_for("sam@vague-co.io", status="verified", checked_days_ago=45, scheduled_in_days=None)

    def qev(request: httpx.Request) -> httpx.Response:
        email = request.url.params["email"]
        name = {"maya@stale-co.io": "qev_rejected_email.json", "sam@vague-co.io": "qev_timeout.json"}.get(
            email, "qev_safe_to_send.json"
        )
        return httpx.Response(200, json=fixture(name))

    api = Api(qev=qev)
    stats = v.run(rc(), verifier=make(api, providers=(v.QEV,)))
    assert sorted(r.url.params["email"] for r in api.requests) == [
        "leo@never-co.io", "maya@stale-co.io", "sam@vague-co.io"
    ]  # fmt: skip
    assert stats["due"] == 3 and stats["status.invalid"] == 1 and stats["status.verified"] == 1
    assert contact_row(stale)["email_status"] == "invalid"  # it would bounce: never sent
    assert contact_row(never)["email_status"] == "verified" and contact_row(never)["email_checked_at"] is not None
    inconclusive = contact_row(vague)
    assert inconclusive["email_status"] == "unknown"  # a guess that cannot be re-confirmed is not sent alone
    assert inconclusive["email_checked_at"] < datetime.now(UTC) - timedelta(days=44)  # still due: tried again
    assert contact_row(fresh)["email_status"] == "verified" and contact_row(later)["email_status"] == "verified"
