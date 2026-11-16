"""The free domain guess before any grounded website lookup (lane E1b, 15 Nov 2026): DNS first, then the home page,
kept only when the page itself names the company; grounded lookups only within the lookup use's allowance."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.models import WebsiteLookup
from nument_engine.pipeline import lookup
from nument_engine.segments import load_segments, sync_segments_to_db

from .sources_helpers import clean_db, insert_business, mock_transport, no_network, run_context

__all__ = ["clean_db", "no_network"]

CARE_NIMBLE = """<html><head><title>Care Nimble | Home care, simplified</title>
<meta property="og:site_name" content="Care Nimble"></head><body><h1>Care that moves with you</h1></body></html>"""
PARKED = """<html><head><title>lithemedical.com</title></head><body>
<p>lithemedical.com is for sale! Buy this domain today.</p></body></html>"""
OTHER_COMPANY = """<html><head><title>Lithe Health | Physiotherapy in Leeds</title></head>
<body>Book a session with our physiotherapists.</body></html>"""
NGINX = "<html><head><title>Welcome to nginx!</title></head><body>Welcome to nginx! carenimble.co</body></html>"


@pytest.fixture(autouse=True)
def _no_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lookup, "PAGE_GAP_S", 0.0)


def fake_dns(answers: dict[str, bool | None]) -> lookup.Resolve:
    async def resolve(domain: str) -> bool | None:
        return answers.get(domain, False)

    return resolve


# ---- pure helpers ----------------------------------------------------------------------------------------


def test_guessed_domains_come_from_the_name_without_its_legal_form() -> None:
    assert lookup.guess_labels("Care Nimble, Inc.") == ["carenimble"]
    assert lookup.guess_labels("CipherSonic Labs Inc.") == ["ciphersoniclabs", "ciphersonic"]
    assert lookup.guess_labels("Peace Coffee PBC") == ["peacecoffee"]
    assert lookup.guess_labels("Café Noir & Co") == ["cafenoir"]
    assert lookup.guess_labels("ABC LLC") == []  # too short to be anyone's in particular
    assert lookup.candidate_domains("Care Nimble, Inc.", "us") == [
        "carenimble.com", "carenimble.io", "carenimble.ai", "carenimble.co", "carenimble.app", "carenimble.us",
    ]  # fmt: skip
    assert lookup.candidate_domains("Brightcart Ltd", "gb")[-2:] == ["brightcart.co.uk", "brightcart.uk"]
    assert lookup.candidate_domains("ABC", "us") == []


@pytest.mark.parametrize(
    ("html", "domains", "expected"),
    [
        (CARE_NIMBLE, {"carenimble.com"}, True),
        ("<title>CareNimble</title>", set(), True),  # joined in the title
        ("<title>Home</title><body>2026 Care Nimble, Inc. All rights reserved.</body>", set(), True),
        ("<title>carenimble.com</title><body>carenimble.com</body>", {"carenimble.com"}, False),  # only the address
        ("<title>Nimble Care Partners</title>", set(), False),  # other words, other order
        ("<title>Care Nimbleness</title>", set(), False),  # not a whole word
    ],
)
def test_the_page_itself_must_name_the_company(html: str, domains: set[str], expected: bool) -> None:
    assert lookup.names_company("Care Nimble, Inc.", html, domains) is expected


def test_a_generic_last_word_may_be_missing_from_the_page() -> None:
    assert lookup.names_company("CipherSonic Labs Inc.", "<title>CipherSonic | Audio AI</title>")
    assert not lookup.names_company("Nova Inc", "<title>Innovations Hub</title>")


def test_parked_and_default_pages_are_recognised() -> None:
    assert lookup.is_parked(PARKED) and lookup.is_parked(NGINX)
    assert not lookup.is_parked(CARE_NIMBLE)


# ---- the guess over the network (mocked) ---------------------------------------------------------------


def run_guess(rows: list[dict[str, Any]], dns: dict[str, bool | None], routes: dict[str, Any]) -> dict[str, Any]:
    transport, _ = mock_transport({"*": (404, "")} | routes)
    countries = {r["id"]: "us" for r in rows}
    return asyncio.run(lookup.guess_sites(rows, countries, resolve=fake_dns(dns), transport=transport))


def test_a_guess_is_kept_only_when_it_resolves_and_its_page_names_the_company() -> None:
    rows = [{"id": "a", "name": "Care Nimble, Inc."}, {"id": "b", "name": "Lithe Medical, Inc."}]
    dns = {"carenimble.co": True, "carenimble.com": True, "lithemedical.com": True, "lithemedical.ai": True}
    routes = {
        "https://carenimble.com/": (200, CARE_NIMBLE),
        "https://carenimble.co/": (200, NGINX),
        "https://lithemedical.com/": (200, PARKED),
        "https://lithemedical.ai/": (200, OTHER_COMPANY),
    }
    out = run_guess(rows, dns, routes)
    assert out["a"] == lookup.Guess("https://carenimble.com/", "found")  # .com is tried first
    assert out["b"] == lookup.Guess(None, "not_found")  # a parked page and another company's site


def test_a_redirect_to_a_domain_marketplace_is_not_the_company() -> None:
    sale = httpx.Response(302, headers={"location": "https://www.hugedomains.com/domain_profile.cfm?d=carenimble"})
    page = (200, "<title>Care Nimble domain</title><body>Care Nimble</body>")
    out = run_guess(
        [{"id": "a", "name": "Care Nimble, Inc."}],
        {"carenimble.com": True},
        {"https://carenimble.com/": sale, "https://www.hugedomains.com/domain_profile.cfm": page},
    )
    assert out["a"].status == "not_found"


def test_dns_or_network_trouble_leaves_the_guess_for_another_night() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    out = run_guess(
        [{"id": "a", "name": "Care Nimble, Inc."}, {"id": "b", "name": "Orcosa Inc."}],
        {"carenimble.com": None, "orcosa.com": True},
        {"https://orcosa.com/robots.txt": (404, ""), "https://orcosa.com/": timeout},
    )
    assert out["a"].status == "unknown" and out["b"].status == "unknown"


def test_a_redirect_to_a_never_fetch_host_is_dropped_quietly() -> None:
    social = httpx.Response(301, headers={"location": "https://www.facebook.com/carenimble"})
    out = run_guess(
        [{"id": "a", "name": "Care Nimble, Inc."}], {"carenimble.com": True}, {"https://carenimble.com/": social}
    )
    assert out["a"].status == "not_found"


# ---- the whole stage --------------------------------------------------------------------------------------


@dataclass
class Answer:
    output: WebsiteLookup
    grounding: dict[str, Any]
    inr: float = 0.3
    tag: str = "gemini:gemini-3.8-flash#find_website.v1"


@dataclass
class Budget:
    left: int

    def grounding_quota_left(self) -> int:
        return self.left


@dataclass
class Router:
    answers: dict[str, Answer]
    budget: Budget
    calls: list[str] = field(default_factory=list)

    def run_result(self, task: str, inputs: dict[str, Any], **_: Any) -> Answer:
        assert task == "find_website"
        self.calls.append(inputs["name"])
        self.budget.left -= 1
        return self.answers[inputs["name"]]


def test_the_stage_guesses_first_then_searches_within_the_allowance(clean_db: str) -> None:
    with db.tx() as conn:
        sync_segments_to_db(conn, {"firms-us": load_segments()["firms-us"]})
    guessed = insert_business(name="Care Nimble, Inc.", segment_id="firms-us", country="us", city=None)
    waiting = insert_business(name="Orcosa Inc.", segment_id="firms-us", country="us", city=None)
    searched = insert_business(name="Lithe Medical, Inc.", segment_id="firms-us", country="us", city=None)  # newest
    cited = {"sources": [{"uri": "https://vertexaisearch.example/r/1", "title": "lithe.health"}], "supports": []}
    router = Router(
        {
            "Lithe Medical, Inc.": Answer(
                WebsiteLookup(website="lithe.health", website_line="Website: lithe.health"), cited
            )
        },
        Budget(left=1),
    )
    transport, _ = mock_transport(
        {
            "*": (404, ""),
            "https://carenimble.com/": (200, CARE_NIMBLE),
            "https://lithe.health": (200, "<title>Lithe Medical | Wearable rehab</title>"),
        }
    )
    stats = lookup.run(
        run_context(segments=["firms-us"]), router, resolve=fake_dns({"carenimble.com": True}), transport=transport
    )
    assert stats["candidates"] == 3 and stats["guess_found"] == 1 and stats["guess_not_found"] == 2
    assert router.calls == ["Lithe Medical, Inc."] and stats["stopped_quota"] == 1  # one search allowed today
    assert stats["found"] == 1 and stats["waiting_search"] == 1
    rows = {
        r["id"]: r
        for r in db.fetch_all(
            "select id::text as id, website, web_domain, extra from public.businesses where id = any(%s::uuid[])",
            [[guessed, searched, waiting]],
        )
    }
    assert rows[guessed]["web_domain"] == "carenimble.com"
    assert rows[guessed]["extra"]["website_lookup_via"] == "domain_guess"
    assert rows[searched]["web_domain"] == "lithe.health"
    assert rows[searched]["extra"]["website_lookup_via"] == "grounded_search"
    assert "website_lookup_at" not in rows[waiting]["extra"] and rows[waiting]["extra"]["website_guess"] == "not_found"

    again = lookup.run(run_context(segments=["firms-us"]), Router({}, Budget(left=0)), resolve=fake_dns({}))
    assert again["candidates"] == 1 and "guess_not_found" not in again  # the guess is never repeated
    assert again["stopped_quota"] == 1


def test_without_a_router_the_guesses_are_still_saved(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with db.tx() as conn:
        sync_segments_to_db(conn, {"firms-us": load_segments()["firms-us"]})
    bid = insert_business(name="Care Nimble, Inc.", segment_id="firms-us", country="us", city=None)
    other = insert_business(name="Orcosa Inc.", segment_id="firms-us", country="us", city=None)

    def no_router(rc: Any) -> Any:
        raise RuntimeError("no AI key in this environment")

    monkeypatch.setattr(lookup.ai, "router_for", no_router)
    transport, _ = mock_transport({"*": (404, ""), "https://carenimble.com/": (200, CARE_NIMBLE)})
    stats = lookup.run(
        run_context(segments=["firms-us"]), resolve=fake_dns({"carenimble.com": True}), transport=transport
    )
    assert stats["skipped_no_router"] == 1 and stats["guess_found"] == 1
    assert db.scalar("select web_domain from public.businesses where id = %s", [bid]) == "carenimble.com"
    assert db.scalar("select extra->>'website_guess' from public.businesses where id = %s", [other]) == "not_found"
