"""Founder emails (lane E3): the ladder from published addresses to checked guesses, and its labels.

No request leaves the machine: pages come from `httpx.MockTransport`, DNS from a fake resolver, search answers
from a fake router and verifier answers from the documented samples in fixtures/e3."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nument_engine import db, http
from nument_engine.models import FounderEmailLookup
from nument_engine.outreach import verifier as checks
from nument_engine.pipeline import founder_emails as fe
from nument_engine.pipeline.runs import Options, RunContext
from nument_engine.segments import load_segments, sync_segments_to_db

from .sources_helpers import clean_db, no_network

__all__ = ["clean_db", "no_network"]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e3"
DOMAIN = "brightcart.io"
SITE = f"https://{DOMAIN}/"
DELIVERABLE, CATCH_ALL, REJECTED, TIMEOUT = (
    "qev_safe_to_send.json", "qev_accept_all.json", "qev_rejected_email.json", "qev_timeout.json"
)  # fmt: skip


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------------------------------
# Names, patterns and labels
# ---------------------------------------------------------------------------------------------------


def test_names_become_address_parts() -> None:
    assert fe.name_parts("Maya Chen") == ("maya", "chen")
    assert fe.name_parts("Dr. José García") == ("jose", "garcia")
    assert fe.name_parts("Maya R. Chen Jr.") == ("maya", "chen")
    assert fe.name_parts("Mary-Jane O'Neil") == ("maryjane", "oneil")
    assert fe.name_parts("Maya (Mae) Chen") == ("maya", "chen")
    for single in ("Maya", "M. C.", "陈美玲 王", "", None):
        assert fe.name_parts(single) is None  # nothing is guessed for these


def test_the_six_patterns_and_reading_them_back() -> None:
    assert [fe.render(p, "maya", "chen") for p in fe.PATTERNS] == [
        "maya", "maya.chen", "mchen", "mayachen", "m.chen", "mayac"
    ]  # fmt: skip
    for pattern in fe.PATTERNS:
        assert fe.infer_pattern(fe.render(pattern, "maya", "chen"), "Maya Chen") == pattern
    assert fe.infer_pattern("chennai", "Maya Chen") is None  # a name part inside a word is not her address
    assert fe.infer_pattern("hello", "Maya Chen") is None
    assert fe.infer_pattern("maya", "Maya") is None  # no last name: never tied


def test_mail_providers_from_mx_hosts() -> None:
    assert fe.mx_provider(["aspmx.l.google.com", "alt1.aspmx.l.google.com"]) == "google"
    assert fe.mx_provider(["brightcart-io.mail.protection.outlook.com."]) == "microsoft"
    assert fe.mx_provider(["mx.zoho.in"]) == "zoho"
    assert fe.mx_provider(["mx1.mailhost.example"]) == "other"
    assert fe.mx_provider([]) == "none"


def answer(result: str, catch_all: bool | None) -> checks.Check:
    return checks.Check("maya@brightcart.io", result, catch_all, checks.QEV, {}, datetime.now(UTC))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("origin", "given", "backed", "catch_all_domain", "expected"),
    [
        ("published", None, False, None, "likely"),  # published, no check possible today
        ("archive", answer("unknown", None), False, None, "likely"),
        ("published", answer("deliverable", False), False, None, "verified"),
        ("published", answer("undeliverable", None), False, None, "invalid"),
        ("store", answer("risky", True), False, None, "likely"),
        ("guess", None, True, None, "unknown"),  # a guess nobody checked
        ("guess", answer("deliverable", False), False, None, "verified"),
        ("guess", answer("risky", True), False, None, "unknown"),  # catch-all without a published pattern
        ("guess", answer("risky", True), True, None, "likely"),
        ("guess", answer("risky", False), True, None, "likely"),
        ("guess", answer("unknown", None), True, None, "unknown"),  # inconclusive is not risky
        ("guess", None, True, True, "likely"),  # a known catch-all domain and a published pattern
        ("guess", answer("undeliverable", None), True, True, "invalid"),
        ("snippet", answer("deliverable", False), False, None, "verified"),
        ("snippet", answer("risky", True), False, None, "unknown"),  # an unconfirmed snippet is not published
        ("snippet", None, False, None, "unknown"),
    ],
)
def test_labels(
    origin: str, given: checks.Check | None, backed: bool, catch_all_domain: bool | None, expected: str
) -> None:
    assert fe.label(origin, given, backed=backed, catch_all_domain=catch_all_domain) == expected


def test_a_deliverable_answer_on_a_catch_all_domain_is_never_verified() -> None:
    odd = checks.Check("maya@brightcart.io", "deliverable", None, checks.QEV, {}, datetime.now(UTC))
    assert fe.label("guess", odd, backed=False, catch_all_domain=None) == "unknown"


def test_quotes_are_cut_from_the_source() -> None:
    text = "Team\n\nMaya Chen, founder.   Write to maya@brightcart.io any time.\nLeo Park, design."
    assert fe.quote_around(text, "maya@brightcart.io") == (
        "Team Maya Chen, founder. Write to maya@brightcart.io any time. Leo Park, design."
    )
    assert fe.quote_around("Reach maya [at] brightcart [dot] io", "maya@brightcart.io") == (
        "Reach maya [at] brightcart [dot] io"
    )
    assert fe.quote_around("nothing here", "maya@brightcart.io") is None
    html = '<p>Founder: <a href="mailto:maya@brightcart.io">maya@brightcart.io</a></p><script>x="leo@a.io"</script>'
    assert fe.page_quote(html, "maya@brightcart.io") == "Founder: maya@brightcart.io"


# ---------------------------------------------------------------------------------------------------
# The stage against the test database
# ---------------------------------------------------------------------------------------------------


@pytest.fixture
def e3_db(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Startup segments in the database, no politeness wait between test requests, and empty E3 tables."""
    monkeypatch.setitem(http.POLICY_GAP_S, "public", 0.0)
    with db.tx() as conn:
        sync_segments_to_db(conn, load_segments())
    db.execute("delete from public.email_checks")
    db.execute("delete from public.email_domains")
    try:
        yield clean_db
    finally:
        db.execute("delete from public.email_checks")
        db.execute("delete from public.email_domains")


def startup(
    *,
    segment: str = "firms-us",
    domain: str = DOMAIN,
    founders: tuple[tuple[str, str], ...] = (("Maya Chen", "Co-founder and CEO"),),
    grade: str = "A",
    founder_source: str = "other",
    verified: bool = True,
    country: str | None = None,
) -> str:
    """A startup business with an A lead and its founders as name-only contacts. Returns the business id."""
    tag = uuid.uuid4().hex[:6]
    with db.tx() as conn:
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, country, website, web_domain, status) "
            "values (%s, %s, %s, %s, %s, %s, 'researched') returning id",
            [segment, f"Brightcart {tag}", f"brightcart {tag}", country or segment[-2:], f"https://{domain}/", domain],
        ).fetchone()
        assert biz is not None
        for name, role in founders:
            conn.execute(
                "insert into public.contacts (business_id, name, role, source, source_url, quote, is_decision_maker, "
                "verified, line) values (%s, %s, %s, %s, 'https://news.example.com/brightcart-raises', %s, true, "
                "%s, 'owner')",
                [biz["id"], name, role, founder_source, f"{name}, {role} of Brightcart, said the round", verified],
            )
        conn.execute(
            "insert into public.leads (business_id, segment_id, grade, pitch_mode, channel) "
            "values (%s, %s, %s, 'fit_only', 'email')",
            [biz["id"], segment, grade],
        )
    return str(biz["id"])


def page(business_id: str, url: str, text: str) -> None:
    db.execute(
        "insert into public.pages (business_id, url, text, http_status) values (%s, %s, %s, 200)",
        [business_id, url, text],
    )


def contacts(business_id: str) -> list[dict[str, Any]]:
    return db.fetch_all(
        "select name, role, email, source, source_url, quote, line, line_why, is_decision_maker, email_status, "
        "email_origin, email_pattern, email_checked_at from public.contacts where business_id = %s "
        "and email is not null order by created_at",
        [business_id],
    )


def attempt(business_id: str) -> dict[str, Any]:
    extra = db.scalar("select extra from public.businesses where id = %s", [business_id])
    record: dict[str, Any] = extra["founder_email"]
    return record


class Api:
    """QuickEmailVerification answers per address (default: rejected)."""

    def __init__(self, answers: dict[str, str] | None = None, default: str = REJECTED) -> None:
        self.answers = answers or {}
        self.default = default
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        email = request.url.params["email"]
        self.asked.append(email)
        return httpx.Response(200, json=fixture(self.answers.get(email, self.default)))


def verifier(api: Api | None) -> checks.Verifier:
    if api is None:
        return checks.Verifier([])  # no keys: nothing can be checked
    return checks.Verifier([checks.QuickEmailVerification("qev-test-key")], transport=httpx.MockTransport(api))


Route = Callable[[httpx.Request], httpx.Response]


class Web:
    """Public pages by URL prefix; robots.txt is missing everywhere (everything allowed)."""

    def __init__(self, routes: dict[str, Route | str] | None = None) -> None:
        self.routes = routes or {}
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.seen.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        for prefix, target in self.routes.items():
            if url.startswith(prefix):
                if callable(target):
                    return target(request)
                return httpx.Response(200, text=target, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="not found")

    def asked(self, prefix: str) -> list[str]:
        return [u for u in self.seen if u.startswith(prefix)]


NOTHING = FounderEmailLookup(email=None, line="Email: unknown")


class Router:
    """A grounded-search fake: one scripted answer for find_founder_email (by default: nothing found)."""

    def __init__(self, output: FounderEmailLookup = NOTHING, grounding: dict[str, Any] | None = None) -> None:
        self.output = output
        self.grounding = grounding or {"queries": ["Maya Chen Brightcart email"], "sources": [], "supports": []}
        self.calls: list[dict[str, Any]] = []
        self.budget = None

    def run_result(self, task: str, inputs: dict[str, Any]) -> Any:
        assert task == fe.TASK
        self.calls.append(inputs)
        return SimpleNamespace(output=self.output, grounding=self.grounding, inr=0.0)


def google_mx(domain: str) -> list[str]:
    return ["aspmx.l.google.com"]


def run_stage(
    *,
    api: Api | None = None,
    web: Web | None = None,
    router: Router | None = None,
    resolver: fe.Resolver = google_mx,
    segments: tuple[str, ...] = ("firms-us", "firms-ca", "firms-gb"),
    dry_run: bool = False,
) -> dict[str, Any]:
    rc = RunContext(
        run_id=str(uuid.uuid4()), kind="manual", opts=Options(segments=list(segments), dry_run=dry_run),
        started_at=datetime.now(UTC),
    )  # fmt: skip
    return fe.run(
        rc,
        router=router or Router(),
        verifier=verifier(api),
        resolver=resolver,
        transport=httpx.MockTransport(web or Web()),
    )


# ---- rung 1: their own site --------------------------------------------------------------------------


def test_an_address_on_their_site_is_checked_and_kept_with_its_evidence(e3_db: str) -> None:
    bid = startup()
    page(bid, f"{SITE}team", "Our team. Maya Chen, CEO: maya@brightcart.io. Say hello@brightcart.io or "
         "write to maya.chen@gmail.com.")  # fmt: skip
    api = Api({"maya@brightcart.io": DELIVERABLE})
    stats = run_stage(api=api)
    assert api.asked == ["maya@brightcart.io"]  # the shared inbox and the free-mail address are never used
    [row] = contacts(bid)
    assert (row["email"], row["email_status"], row["email_origin"], row["email_pattern"]) == (
        "maya@brightcart.io", "verified", "published", "first"
    )  # fmt: skip
    assert row["source"] == "website" and row["source_url"] == f"{SITE}team" and row["line"] == "owner"
    assert "maya@brightcart.io" in row["quote"] and row["is_decision_maker"] and row["email_checked_at"]
    assert row["name"] == "Maya Chen" and row["role"] == "Co-founder and CEO"
    assert attempt(bid)["outcome"] == "found" and attempt(bid)["checks"] == 1
    assert stats["found.verified"] == 1 and stats["skipped.free_mail"] == 1 and stats["skipped.shared_inbox"] == 1


def test_a_published_address_is_likely_when_nothing_can_check_it(e3_db: str) -> None:
    bid = startup()
    page(bid, f"{SITE}contact", "Founder: Maya Chen (maya@brightcart.io)")
    run_stage(api=None)
    [row] = contacts(bid)
    assert row["email_status"] == "likely" and row["email_checked_at"] is None  # re-checked before sending


def test_a_published_address_that_bounces_is_never_used(e3_db: str) -> None:
    bid = startup()
    db.execute(
        "insert into public.contacts (business_id, name, email, source, source_url, quote, verified) "
        "values (%s, 'Maya Chen', 'maya@brightcart.io', 'website', %s, 'maya@brightcart.io', true)",
        [bid, f"{SITE}contact"],
    )
    api = Api({"maya@brightcart.io": REJECTED, "maya.chen@brightcart.io": DELIVERABLE})
    run_stage(api=api)
    rows = {r["email"]: r for r in contacts(bid)}
    assert rows["maya@brightcart.io"]["email_status"] == "invalid"  # the stored contact is marked, not deleted
    assert rows["maya.chen@brightcart.io"]["email_status"] == "verified"
    assert rows["maya.chen@brightcart.io"]["email_origin"] == "guess"
    assert api.asked == ["maya@brightcart.io", "maya.chen@brightcart.io"]  # first@ was not checked twice


def test_an_existing_contact_with_the_address_is_updated_not_duplicated(e3_db: str) -> None:
    bid = startup()
    db.execute(
        "insert into public.contacts (business_id, email, source, source_url, quote, verified) "
        "values (%s, 'maya@brightcart.io', 'website', %s, 'Mail maya@brightcart.io', true)",
        [bid, f"{SITE}contact"],
    )
    run_stage(api=Api({"maya@brightcart.io": DELIVERABLE}))
    [row] = contacts(bid)
    assert row["name"] == "Maya Chen" and row["email_status"] == "verified" and row["line"] == "owner"
    assert row["quote"] == "Mail maya@brightcart.io"  # the address keeps its own evidence


# ---- rung 2: old copies of their site ----------------------------------------------------------------


def wayback(index: list[list[str]], snapshots: dict[str, str]) -> dict[str, Route | str]:
    routes: dict[str, Route | str] = {
        fe.WAYBACK_CDX: lambda request: httpx.Response(200, json=[["timestamp", "original"], *index]),
    }
    for url, html in snapshots.items():
        routes[url] = html
    return routes


def test_an_old_copy_of_their_team_page(e3_db: str) -> None:
    bid = startup()
    snap = f"{fe.WAYBACK_WEB}/20250301000000id_/https://brightcart.io/team"
    web = Web(wayback(
        [["20250301000000", "https://brightcart.io/team"], ["20250302000000", "https://brightcart.io/blog/post-1"],
         ["20250303000000", "https://other.example/team"]],
        {snap: '<p>Maya Chen <a href="mailto:maya.chen@brightcart.io">maya.chen@brightcart.io</a></p>'},
    ))  # fmt: skip
    api = Api({"maya.chen@brightcart.io": CATCH_ALL})
    run_stage(api=api, web=web)
    [row] = contacts(bid)
    assert (row["email"], row["email_status"], row["email_origin"]) == (
        "maya.chen@brightcart.io", "likely", "archive"
    )  # catch-all, but she published it  # fmt: skip
    assert row["source_url"] == f"{fe.WAYBACK_WEB}/20250301000000/https://brightcart.io/team"
    assert row["quote"] == "Maya Chen maya.chen@brightcart.io" and row["source"] == "other"
    assert not web.asked(f"{fe.WAYBACK_WEB}/20250302")  # only contact, about and team pages are read
    index_url = web.asked(fe.WAYBACK_CDX)[0]
    assert "url=brightcart.io&matchType=domain" in index_url and "collapse=urlkey" in index_url


def test_a_blocked_archive_is_left_for_the_run_and_the_lead_is_retried(e3_db: str) -> None:
    first, second = startup(), startup(domain="leafcart.io")
    web = Web({fe.WAYBACK_CDX: lambda request: httpx.Response(429, text="slow down")})
    stats = run_stage(api=Api(), web=web)
    assert len(web.asked(fe.WAYBACK_CDX)) == 1  # the second lead never asked again
    assert attempt(first)["outcome"] == "deferred" and "archive_blocked" in attempt(first)["deferred"]
    assert attempt(second)["outcome"] in ("deferred", "not_found")
    assert stats["outcome.deferred"] >= 1


# ---- rung 3: search snippets -------------------------------------------------------------------------

REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
LINE = "Email: maya@brightcart.io, written on The Grocer Podcast episode page"


def snippet(email: str = "maya@brightcart.io", line: str = LINE, backed: str | None = None) -> Router:
    support = backed if backed is not None else f"{line}"
    return Router(
        FounderEmailLookup(email=email, line=line),
        {"queries": ["Maya Chen Brightcart email"], "sources": [{"uri": REDIRECT, "title": "grocerpodcast.example"}],
         "supports": [{"text": support, "chunks": [0]}]},
    )  # fmt: skip


def redirect_to(target: str) -> Route:
    return lambda request: httpx.Response(302, headers={"location": target})


def test_a_snippet_confirmed_on_the_cited_page_counts_as_published(e3_db: str) -> None:
    bid = startup()
    episode = "https://grocerpodcast.example/ep/12"
    web = Web({REDIRECT: redirect_to(episode), episode: "<p>Reach Maya at maya@brightcart.io.</p>"})
    router = snippet()
    run_stage(api=Api({"maya@brightcart.io": CATCH_ALL}), web=web, router=router)
    assert router.calls == [{"name": "Maya Chen", "company": router.calls[0]["company"], "domain": DOMAIN,
                             "country": "the US"}]  # fmt: skip
    [row] = contacts(bid)
    assert (row["email_origin"], row["email_status"], row["source_url"]) == ("post", "likely", episode)
    assert row["quote"] == "Reach Maya at maya@brightcart.io."


def test_an_unconfirmed_snippet_needs_a_deliverable_answer(e3_db: str) -> None:
    linkedin = "https://www.linkedin.com/in/maya-chen"
    web = Web({REDIRECT: redirect_to(linkedin)})
    bid = startup()
    run_stage(api=Api({"maya@brightcart.io": CATCH_ALL}), web=web, router=snippet())
    assert contacts(bid) == []  # catch-all and nobody published the pattern: unknown, never stored
    assert not web.asked("https://www.linkedin.com")  # LinkedIn is never fetched
    other = startup(domain="leafcart.io")
    run_stage(api=Api({"maya@leafcart.io": DELIVERABLE}), web=web, router=snippet("maya@leafcart.io",
              "Email: maya@leafcart.io, on LinkedIn"))  # fmt: skip
    [row] = contacts(other)
    assert (row["email_origin"], row["email_status"], row["source_url"]) == ("snippet", "verified", linkedin)


@pytest.mark.parametrize(
    ("email", "line", "backed", "why"),
    [
        ("maya@brightcart.io", LINE, "Maya Chen founded Brightcart in 2025.", "unbacked"),  # address not backed
        ("maya@brightcart.co", "Email: maya@brightcart.co, on a forum", None, "rejected"),  # not their domain
        ("hello@brightcart.io", "Email: hello@brightcart.io, on their site", None, "rejected"),  # a shared inbox
        ("leo@brightcart.io", "Email: leo@brightcart.io, on their site", None, "not_theirs"),  # not the founder's
        ("maya@brightcart.io", "Email: unknown", None, "none"),  # the line does not show it
    ],
)
def test_snippets_that_are_not_kept(e3_db: str, email: str, line: str, backed: str | None, why: str) -> None:
    bid = startup()
    stats = run_stage(api=Api(default=REJECTED), router=snippet(email, line, backed))
    assert stats[f"snippet.{why}"] == 1 and stats.get("snippet.confirmed", 0) == 0
    assert contacts(bid) == []  # nothing kept (the guesses were all rejected)


def test_no_search_without_allowance(e3_db: str) -> None:
    db.set_setting("grounding.email_snippets_per_day", 0)
    bid = startup()
    router = snippet()
    run_stage(api=Api(), router=router)
    assert router.calls == [] and "snippet_allowance" in attempt(bid)["deferred"]
    assert attempt(bid)["outcome"] == "deferred"


# ---- rungs 4 and 5: app store and filings ------------------------------------------------------------


def test_the_play_store_developer_contact(e3_db: str) -> None:
    bid = startup()
    db.execute(
        "insert into public.facts (business_id, field, value, quote, url, model, verified, verified_at) "
        "values (%s, 'probe.app_links', %s, 'assetlinks', %s, 'rule', true, now())",
        [bid, db.Jsonb({"ios_app_ids": [], "android_packages": ["io.brightcart.app"]}), f"{SITE}.well-known"],
    )
    listing = f"{fe.PLAY_DETAILS}?id=io.brightcart.app&hl=en"
    web = Web({listing: "<div>App support</div><div>Email maya@brightcart.io</div>"})
    run_stage(api=Api({"maya@brightcart.io": DELIVERABLE}), web=web)
    [row] = contacts(bid)
    assert (row["email_origin"], row["email_status"], row["source_url"]) == ("store", "verified", listing)


def test_an_address_in_a_registry_record(e3_db: str) -> None:
    bid = startup()
    db.execute(
        "insert into public.contacts (business_id, email, source, source_url, quote, verified) "
        "values (%s, 'mchen@brightcart.io', 'registry', 'https://registry.example/123', 'mchen@brightcart.io', true)",
        [bid],
    )
    run_stage(api=Api({"mchen@brightcart.io": DELIVERABLE}))
    [row] = contacts(bid)
    assert (row["email_origin"], row["email_status"], row["email_pattern"]) == ("filing", "verified", "flast")


# ---- rung 6: guesses ---------------------------------------------------------------------------------


def test_guesses_go_pattern_by_pattern_until_one_is_deliverable(e3_db: str) -> None:
    bid = startup()
    api = Api({"maya.chen@brightcart.io": DELIVERABLE})
    run_stage(api=api)
    assert api.asked == ["maya@brightcart.io", "maya.chen@brightcart.io"]
    [row] = contacts(bid)
    assert (row["email"], row["email_status"], row["email_origin"], row["email_pattern"]) == (
        "maya.chen@brightcart.io", "verified", "guess", "first.last"
    )  # fmt: skip
    # a guess has no page of its own: it sits on the founder's row, which keeps the name's evidence
    assert row["source_url"] == "https://news.example.com/brightcart-raises" and "Maya Chen" in row["quote"]
    assert db.scalar("select count(*) from public.contacts where business_id = %s", [bid]) == 1
    domain = db.fetch_one("select * from public.email_domains where domain = %s", [DOMAIN])
    assert domain is not None and domain["mx_provider"] == "google" and domain["catch_all"] is False


def test_a_published_colleague_shows_the_pattern(e3_db: str) -> None:
    bid = startup()
    page(bid, f"{SITE}about", "Leo Park, design lead: leo.park@brightcart.io")
    db.execute(
        "insert into public.contacts (business_id, name, role, source, verified) "
        "values (%s, 'Leo Park', 'Design lead', 'website', true)",
        [bid],
    )
    api = Api({"maya.chen@brightcart.io": CATCH_ALL})
    router = snippet()
    run_stage(api=api, router=router)
    assert api.asked == ["maya.chen@brightcart.io"] and router.calls == []  # backed: no search needed
    [row] = [r for r in contacts(bid) if r["email"].startswith("maya")]
    assert (row["email_status"], row["email_pattern"]) == ("likely", "first.last")


def test_a_catch_all_domain_without_a_published_pattern_gives_nothing(e3_db: str) -> None:
    bid = startup()
    api = Api(default=CATCH_ALL)
    run_stage(api=api)
    assert api.asked == ["maya@brightcart.io"] and contacts(bid) == []  # one check showed catch-all: stop
    assert attempt(bid)["outcome"] == "not_found"
    assert db.scalar("select catch_all from public.email_domains where domain = %s", [DOMAIN]) is True
    second = startup(segment="firms-gb")  # the same domain, seen again (one business per domain and segment)
    again = Api(default=CATCH_ALL)
    run_stage(api=again)
    assert again.asked == [] and contacts(second) == []  # the domain is remembered as catch-all


def test_at_most_five_checks_per_lead(e3_db: str) -> None:
    bid = startup(founders=(("Maya Chen", "CEO"), ("Leo Park", "Co-founder")))
    api = Api()  # everything rejected
    run_stage(api=api)
    assert len(api.asked) == fe.MAX_CHECKS
    assert attempt(bid)["checks"] == fe.MAX_CHECKS and attempt(bid)["outcome"] == "not_found"
    db.execute(
        "update public.businesses set extra = jsonb_set(extra, '{founder_email,next_at}', to_jsonb(%s::text)) "
        "where id = %s",
        [(datetime.now(UTC) - timedelta(minutes=1)).isoformat(), bid],
    )
    again = Api({"leo@brightcart.io": DELIVERABLE})
    run_stage(api=again)
    assert again.asked == []  # the five checks of this 30-day window are spent


def test_an_inconclusive_answer_defers_the_lead(e3_db: str) -> None:
    bid = startup()
    api = Api(default=TIMEOUT)
    run_stage(api=api)
    assert api.asked == ["maya@brightcart.io"]
    record = attempt(bid)
    assert record["outcome"] == "deferred" and "inconclusive" in record["deferred"]
    retry = datetime.fromisoformat(record["next_at"]) - datetime.fromisoformat(record["at"])
    assert retry == fe.RETRY["deferred"]


def test_cached_answers_are_reused(e3_db: str) -> None:
    db.execute(
        "insert into public.email_checks (email, result, provider, raw, checked_at) values (%s, 'deliverable', %s, "
        "%s, now() - interval '3 days')",
        ["maya@brightcart.io", checks.QEV, db.Jsonb({"catch_all": False, "fields": {}})],
    )
    bid = startup()
    api = Api()
    run_stage(api=api)
    assert api.asked == [] and contacts(bid)[0]["email_status"] == "verified"
    assert attempt(bid)["checks"] == 0


def test_no_guesses_in_published_only_countries(e3_db: str) -> None:
    bid = startup(segment="firms-ca")
    api = Api({"maya@brightcart.io": DELIVERABLE})
    stats = run_stage(api=api)
    assert api.asked == [] and contacts(bid) == []
    assert stats["guess.published_only_country"] == 1


def test_no_guesses_without_mail_servers_or_on_free_builders(e3_db: str) -> None:
    bid = startup()
    api = Api({"maya@brightcart.io": DELIVERABLE})
    run_stage(api=api, resolver=lambda domain: [])
    assert api.asked == [] and contacts(bid) == []
    flaky = startup(domain="leafcart.io")
    run_stage(api=api, resolver=lambda domain: None)
    assert "dns" in attempt(flaky)["deferred"]
    builder = startup(domain="brightcart.wixsite.com")
    run_stage(api=api)
    assert api.asked == [] and contacts(builder) == []


def test_a_guess_stored_earlier_is_never_read_back_as_published(e3_db: str) -> None:
    bid = startup(founder_source="website")
    db.execute(
        "update public.contacts set email = 'maya@brightcart.io', email_status = 'unknown', email_origin = 'guess', "
        "email_pattern = 'first' where business_id = %s",
        [bid],
    )
    api = Api(default=CATCH_ALL)
    run_stage(api=api)
    [row] = contacts(bid)
    assert row["email_status"] == "unknown"  # a catch-all answer for an unbacked guess stays unknown


# ---- who is a candidate ------------------------------------------------------------------------------


def test_suppression_do_not_contact_and_finished_leads(e3_db: str) -> None:
    suppressed = startup()
    page(suppressed, f"{SITE}team", "Maya Chen maya@brightcart.io")
    db.execute("insert into public.suppression (email, reason) values ('maya@brightcart.io', 'opt_out')")
    blocked = startup(domain="leafcart.io")
    db.execute("insert into public.suppression (web_domain, reason) values ('leafcart.io', 'founder_skip')")
    no_founder = startup(domain="oakcart.io")
    db.execute("update public.contacts set do_not_contact = true where business_id = %s", [no_founder])
    done = startup(domain="elmcart.io")
    db.execute(
        "insert into public.contacts (business_id, name, email, source, is_decision_maker, line, email_status) "
        "values (%s, 'Maya Chen', 'maya@elmcart.io', 'website', true, 'owner', 'verified')",
        [done],
    )
    c_grade = startup(domain="ashcart.io", grade="C")
    api = Api(default=REJECTED)
    stats = run_stage(api=api)
    assert "maya@brightcart.io" not in api.asked and stats["skipped.suppressed"] >= 1
    assert attempt(blocked)["outcome"] == "no_domain" and attempt(no_founder)["outcome"] == "no_founder"
    assert not any(e.endswith(("@leafcart.io", "@oakcart.io", "@elmcart.io", "@ashcart.io")) for e in api.asked)
    for untouched in (done, c_grade):
        assert "founder_email" not in db.scalar("select extra from public.businesses where id = %s", [untouched])


def test_a_dry_run_only_counts(e3_db: str) -> None:
    bid = startup()
    api = Api({"maya@brightcart.io": DELIVERABLE})
    stats = run_stage(api=api, dry_run=True)
    assert stats == {"candidates": 1} and api.asked == []
    assert "founder_email" not in db.scalar("select extra from public.businesses where id = %s", [bid])


def test_a_name_no_source_confirms_gets_published_addresses_but_no_guesses(e3_db: str) -> None:
    unconfirmed = startup(verified=False)
    api = Api({"maya@brightcart.io": DELIVERABLE})
    run_stage(api=api)
    assert api.asked == [] and contacts(unconfirmed) == []  # a guess would rest on the name alone
    published = startup(domain="leafcart.io", verified=False)
    page(published, "https://leafcart.io/team", "Maya Chen runs Leafcart: maya@leafcart.io")
    run_stage(api=Api({"maya@leafcart.io": DELIVERABLE}))
    [row] = contacts(published)
    assert (row["email_origin"], row["email_status"]) == ("published", "verified")


def test_a_country_we_never_write_to_is_left_alone(e3_db: str) -> None:
    bid = startup(country="de")  # a German company in a US segment (should never happen): left alone
    page(bid, f"{SITE}team", "Maya Chen maya@brightcart.io")
    api = Api({"maya@brightcart.io": DELIVERABLE})
    run_stage(api=api)
    assert api.asked == [] and contacts(bid) == [] and attempt(bid)["outcome"] == "country"


def test_an_address_marked_do_not_contact_is_never_used_again(e3_db: str) -> None:
    bid = startup()
    db.execute(
        "insert into public.contacts (business_id, name, email, source, do_not_contact) "
        "values (%s, 'Maya Chen', 'maya@brightcart.io', 'website', true)",
        [bid],
    )
    page(bid, f"{SITE}team", "Maya Chen, CEO: maya@brightcart.io")
    api = Api({"maya@brightcart.io": DELIVERABLE})
    stats = run_stage(api=api)
    assert "maya@brightcart.io" not in api.asked and stats["skipped.do_not_contact"] >= 1
    assert db.scalar(
        "select email_status from public.contacts where business_id = %s and email = 'maya@brightcart.io'", [bid]
    ) == "unknown"  # fmt: skip
