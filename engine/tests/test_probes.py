"""Startup probes (E2a, 15 Nov 2026): every probe's success and failure paths (timeout, 404, malformed answer,
block), the acceptance rules for GitHub organisations and apps, robots.txt for crt.sh, the GitHub request cap and
the per-startup orchestration.

Fixtures under fixtures/e2a/probes: rdap_domain, itunes_lookup, aasa and assetlinks are trimmed real answers
(company data only); crtsh, wayback_cdx, github_* and itunes_search follow the real formats with invented values
(no person's data).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine.research import probes as pr

from .sources_helpers import mock_transport, no_network

__all__ = ["no_network"]

FIX = Path(__file__).resolve().parent / "fixtures" / "e2a" / "probes"
SITE = "https://tallyhq-nlead.io"


def fixture(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def raw(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def target(**kw: Any) -> pr.Target:
    base: dict[str, Any] = {
        "business_id": "b-1",
        "name": "TallyHQ",
        "host": "tallyhq-nlead.io",
        "domain": "tallyhq-nlead.io",
        "country": "in",
    }
    base.update(kw)
    return pr.Target(**base)


class FakeResolver:
    def __init__(self, answers: dict[tuple[str, str], Any], delay: float = 0.0) -> None:
        self.answers, self.delay, self.calls = answers, delay, []

    async def query(self, name: str, rdtype: str) -> list[str] | None:
        self.calls.append((name, rdtype))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.answers.get((name, rdtype), [])


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


async def probe(
    name: str, routes: dict[str, Any], t: pr.Target | None = None, **kw: Any
) -> tuple[pr.Outcome, list[httpx.Request]]:
    transport, seen = mock_transport(routes)
    async with pr.Probes(transport=transport, resolver=kw.pop("resolver", FakeResolver({})), **kw) as p:
        for http in (p.rdap, p.crtsh, p.wayback, p.github_http, p.itunes, p.sites):
            http.min_gap = 0.0
        outcome = await p.run(name, t or target())
    return outcome, seen


# ---- domain age, first certificate, first capture -----------------------------------------------------------

RDAP_REDIRECT = {
    "https://rdap.org/domain/tallyhq-nlead.io": httpx.Response(
        302, headers={"location": "https://rdap.registry-nlead.example/domain/tallyhq-nlead.io"}
    )
}


async def test_rdap_follows_the_bootstrap_and_reads_the_registration() -> None:
    routes = {
        **RDAP_REDIRECT,
        "https://rdap.registry-nlead.example/domain/tallyhq-nlead.io": (200, fixture("rdap_domain.json")),
    }
    outcome, seen = await probe("domain_created", routes)
    assert outcome.state == "ok"
    assert outcome.value == {"date": "1995-09-12", "registrar": "SafeNames Ltd."}
    assert outcome.url == "https://rdap.registry-nlead.example/domain/tallyhq-nlead.io"
    assert outcome.quote == '{"eventAction":"registration","eventDate":"1995-09-12T04:00:00Z"}'
    assert not any(r.url.path == "/robots.txt" for r in seen)  # an official API: no robots.txt


@pytest.mark.parametrize(
    ("answer", "state"),
    [
        ((404, ""), "none"),  # no RDAP server for the TLD, or no such domain
        (timeout, "error"),
        ((200, "<html>not json</html>"), "error"),
        ((200, {"events": [{"eventAction": "expiration", "eventDate": "2030-01-01T00:00:00Z"}]}), "none"),
        ((200, ["not", "an", "object"]), "error"),
        ((429, "slow down"), "skipped"),
    ],
)
async def test_rdap_failures_write_nothing(answer: Any, state: str) -> None:
    routes = {**RDAP_REDIRECT, "https://rdap.registry-nlead.example/domain/tallyhq-nlead.io": answer}
    outcome, _ = await probe("domain_created", routes)
    assert outcome.state == state and outcome.value is None


async def test_crtsh_obeys_robots_txt() -> None:
    """crt.sh is not an official API and its robots.txt disallows everything: the probe never reads it."""
    routes = {
        "https://crt.sh/robots.txt": (200, "User-agent: *\nDisallow: /"),
        "https://crt.sh/": (200, fixture("crtsh.json")),
    }
    outcome, seen = await probe("first_cert", routes)
    assert outcome.state == "robots" and outcome.value is None
    assert [r.url.path for r in seen] == ["/robots.txt"]


@pytest.mark.parametrize(
    ("answer", "state", "value"),
    [
        ((200, fixture("crtsh.json")), "ok", {"date": "2024-03-02"}),
        ((200, []), "none", None),
        ((404, ""), "none", None),
        ((200, "{broken"), "error", None),
        (timeout, "error", None),
    ],
)
async def test_crtsh_earliest_certificate_where_robots_allows(answer: Any, state: str, value: Any) -> None:
    routes = {"https://crt.sh/robots.txt": (404, ""), "https://crt.sh/": answer}
    outcome, _ = await probe("first_cert", routes)
    assert outcome.state == state and outcome.value == value
    if state == "ok":
        assert '"not_before":"2024-03-02T09:03:12"' in outcome.quote and outcome.url and "output=json" in outcome.url


@pytest.mark.parametrize(
    ("answer", "state", "value"),
    [
        ((200, raw("wayback_cdx.json")), "ok", {"date": "2024-03-05"}),
        ((200, "[]"), "none", None),
        ((404, ""), "none", None),
        ((200, '[["timestamp"],["not-a-date"]]'), "error", None),
        ((200, "<html>maintenance</html>"), "error", None),
        (timeout, "error", None),
        ((503, "busy"), "skipped", None),
    ],
)
async def test_wayback_first_capture(answer: Any, state: str, value: Any) -> None:
    outcome, seen = await probe("first_capture", {"https://web.archive.org/cdx/search/cdx": answer})
    assert outcome.state == state and outcome.value == value
    if state == "ok":
        assert outcome.quote == "20240305121314 https://tallyhq-nlead.io/ 200"
        assert seen[0].url.params["url"] == "tallyhq-nlead.io" and seen[0].url.params["limit"] == "1"


# ---- DNS ----------------------------------------------------------------------------------------------------


async def test_dns_mail_provider_and_tool_hints() -> None:
    resolver = FakeResolver(
        {
            ("tallyhq-nlead.io", "MX"): ["1 aspmx.l.google.com", "5 alt1.aspmx.l.google.com"],
            ("tallyhq-nlead.io", "TXT"): [
                "v=spf1 include:_spf.google.com include:sendgrid.net ~all",
                "stripe-verification=0123456789abcdef",
                "openai-domain-verification=dv-abc123",
                "some-unknown-token=xyz",
            ],
        }
    )
    outcome, seen = await probe("dns", {}, resolver=resolver)
    assert outcome.state == "ok" and seen == []
    assert outcome.value == {"mx_provider": "google", "txt_hints": ["google_workspace", "openai", "sendgrid", "stripe"]}
    assert outcome.url == "dns:tallyhq-nlead.io"
    assert outcome.quote.startswith("MX 1 aspmx.l.google.com") and "stripe-verification" in outcome.quote


@pytest.mark.parametrize(
    ("mx", "provider"),
    [
        (["0 tallyhq-nlead-io.mail.protection.outlook.com"], "microsoft"),
        (["10 mx.zoho.in", "20 mx2.zoho.in"], "zoho"),
        (["10 mx1.privateemail.com"], "other"),
        (["0 ."], "none"),  # a null MX: the domain takes no mail
        ([], "none"),
    ],
)
def test_mx_providers(mx: list[str], provider: str) -> None:
    assert pr.mx_provider(mx) == provider


async def test_dns_failure_writes_nothing() -> None:
    resolver = FakeResolver({("tallyhq-nlead.io", "MX"): None})
    outcome, _ = await probe("dns", {}, resolver=resolver)
    assert outcome.state == "error" and outcome.value is None


# ---- GitHub -------------------------------------------------------------------------------------------------

API = "https://api.github.com"


def github_routes(org: dict[str, Any] | None = None, login: str = "tallyhq-nlead") -> dict[str, Any]:
    return {
        f"{API}/orgs/{login}": (200, org or fixture("github_org.json")),
        f"{API}/orgs/{login}/repos": (200, fixture("github_repos.json")),
        f"{API}/orgs/{login}/public_members": (200, fixture("github_members.json")),
    }


async def test_github_reads_the_linked_organisation() -> None:
    outcome, seen = await probe("github", github_routes(), target(github=["tallyhq-nlead"]))
    assert outcome.state == "ok"
    assert outcome.value == {"org": "tallyhq-nlead", "public_repos": 3, "last_push": "2026-11-01", "members_public": 2}
    assert outcome.url == f"{API}/orgs/tallyhq-nlead"
    assert "member-one" not in outcome.quote  # member logins are counted, never stored
    paths = [r.url.path for r in seen]
    assert paths == ["/orgs/tallyhq-nlead", "/orgs/tallyhq-nlead/repos", "/orgs/tallyhq-nlead/public_members"]
    assert not any("commits" in p or "events" in p for p in paths)
    assert seen[0].headers["accept"] == "application/vnd.github+json"


async def test_a_linked_organisation_of_someone_else_is_not_the_startups() -> None:
    other = {**fixture("github_org.json"), "login": "vercel", "name": "Vercel", "blog": "https://vercel.com"}
    routes = {f"{API}/orgs/vercel": (200, other), f"{API}/orgs/tallyhq-nlead": (404, "")}
    outcome, seen = await probe("github", routes, target(github=["vercel"]))
    assert outcome.state == "none"
    assert [r.url.path for r in seen] == ["/orgs/vercel", "/orgs/tallyhq-nlead"]  # then the guess, which is missing


async def test_a_guessed_organisation_counts_only_when_its_profile_links_back() -> None:
    elsewhere = {**fixture("github_org.json"), "blog": "https://someone-else.example"}
    outcome, seen = await probe("github", {f"{API}/orgs/tallyhq-nlead": (200, elsewhere)})
    assert outcome.state == "none" and len(seen) == 1  # same name, different site: not theirs
    outcome, _ = await probe("github", github_routes())
    assert outcome.state == "ok" and outcome.value is not None and outcome.value["org"] == "tallyhq-nlead"


async def test_an_organisation_without_repositories_skips_the_repository_call() -> None:
    empty = {**fixture("github_org.json"), "public_repos": 0}
    outcome, seen = await probe("github", github_routes(empty), target(github=["tallyhq-nlead"]))
    assert outcome.value == {"org": "tallyhq-nlead", "public_repos": 0, "last_push": None, "members_public": 2}
    assert "/orgs/tallyhq-nlead/repos" not in [r.url.path for r in seen]


async def test_the_github_request_cap_and_the_rate_limit_stop_github() -> None:
    outcome, seen = await probe("github", github_routes(), target(github=["tallyhq-nlead"]), github_requests=1)
    assert outcome.state == "skipped" and "cap" in outcome.reason and len(seen) == 1
    limited = {f"{API}/orgs/tallyhq-nlead": (403, '{"message": "API rate limit exceeded"}')}
    transport, seen = mock_transport(limited)
    async with pr.Probes(transport=transport, resolver=FakeResolver({})) as p:
        p.github_http.min_gap = 0.0
        first = await p.run("github", target(github=["tallyhq-nlead"]))
        second = await p.run("github", target(business_id="b-2", github=["tallyhq-nlead"]))
    assert first.state == "skipped" and second.state == "skipped"
    assert len(seen) == 1  # after the rate limit no request reaches GitHub this run


@pytest.mark.parametrize("answer", [timeout, (200, "{not json"), (200, ["a", "list"])])
async def test_github_failures_are_errors(answer: Any) -> None:
    outcome, _ = await probe("github", {f"{API}/orgs/tallyhq-nlead": answer}, target(github=["tallyhq-nlead"]))
    assert outcome.state == "error" and outcome.value is None


# ---- app links and the App Store ------------------------------------------------------------------------------

AASA = f"{SITE}/.well-known/apple-app-site-association"
ASSETLINKS = f"{SITE}/.well-known/assetlinks.json"


async def test_app_links_from_the_sites_own_files() -> None:
    routes = {f"{SITE}/robots.txt": (404, ""), AASA: (200, raw("aasa.json")), ASSETLINKS: (200, raw("assetlinks.json"))}
    outcome, _ = await probe("app_links", routes)
    assert outcome.state == "ok"
    assert outcome.value == {
        "ios_app_ids": ["LBQJ96FQ8D.so.notion.NotionAI.Prod", "LBQJ96FQ8D.notion.id"],
        "android_packages": ["notion.id"],
    }
    assert outcome.url == AASA and '"package_name":["notion.id"]' in outcome.quote


@pytest.mark.parametrize(
    ("aasa", "links", "state"),
    [
        ((404, ""), (404, ""), "none"),
        ((200, "<!doctype html><html>Page not found</html>"), (200, "<html></html>"), "none"),  # soft 404
        ((200, "{broken json"), (404, ""), "error"),
        (timeout, (404, ""), "error"),
        ((404, ""), (200, '[{"target": {"namespace": "web"}}]'), "none"),
    ],
)
async def test_app_links_failures(aasa: Any, links: Any, state: str) -> None:
    routes = {f"{SITE}/robots.txt": (404, ""), AASA: aasa, ASSETLINKS: links}
    outcome, _ = await probe("app_links", routes)
    assert outcome.state == state and outcome.value is None


async def test_app_links_obey_robots_txt() -> None:
    routes = {f"{SITE}/robots.txt": (200, "User-agent: *\nDisallow: /.well-known/"), AASA: (200, raw("aasa.json"))}
    outcome, seen = await probe("app_links", routes)
    assert outcome.state == "robots" and [r.url.path for r in seen] == ["/robots.txt"]


async def test_the_app_store_by_a_linked_id_with_the_sellers_site() -> None:
    notion = target(name="Notion", host="www.notion.so", domain="notion.so", country="us", app_store=["1232780281"])
    routes = {"https://itunes.apple.com/lookup": (200, fixture("itunes_lookup.json"))}
    transport, seen = mock_transport(routes)
    async with pr.Probes(transport=transport, resolver=FakeResolver({})) as p:
        p.itunes.min_gap = 0.0
        outcome = await p.app_store(notion)
    assert outcome.state == "ok"
    assert outcome.value == {
        "name": "Notion: Notes, Tasks, AI",
        "seller": "Notion Labs, Incorporated",
        "url": "https://apps.apple.com/us/app/notion-notes-tasks-ai/id1232780281",
        "released": "2017-09-14",
    }
    assert seen[0].url.params["id"] == "1232780281" and outcome.url and "lookup?id=1232780281" in outcome.url


async def test_the_app_store_by_the_bundle_named_in_the_aasa_file() -> None:
    lookup = fixture("itunes_lookup.json")
    lookup["results"][0]["sellerUrl"] = "https://elsewhere.example"  # trusted anyway: the site named this app
    transport, seen = mock_transport({"https://itunes.apple.com/lookup": (200, lookup)})
    async with pr.Probes(transport=transport, resolver=FakeResolver({})) as p:
        p.itunes.min_gap = 0.0
        outcome = await p.app_store(
            target(name="Notion", host="www.notion.so", domain="notion.so"), ["LBQJ96FQ8D.notion.id"]
        )
    assert outcome.state == "ok" and seen[0].url.params["bundleId"] == "notion.id"


async def test_an_app_search_keeps_only_an_app_sold_from_the_startups_site() -> None:
    routes = {"https://itunes.apple.com/search": (200, fixture("itunes_search.json"))}
    outcome, seen = await probe("app_store", routes)
    assert outcome.state == "ok" and outcome.value is not None
    assert outcome.value["name"] == "TallyHQ: Invoices" and outcome.value["released"] == "2025-06-20"
    assert seen[0].url.params["term"] == "TallyHQ" and seen[0].url.params["country"] == "in"
    stranger = target(host="quillworks-nlead.org", domain="quillworks-nlead.org", name="Quillworks")
    outcome, _ = await probe("app_store", routes, stranger)
    assert outcome.state == "none"  # same-sounding apps of other sellers are never the startup's


async def test_a_linked_app_of_another_company_falls_back_to_the_search() -> None:
    routes = {
        "https://itunes.apple.com/lookup": (200, fixture("itunes_lookup.json")),  # Notion, linked from the page
        "https://itunes.apple.com/search": (200, {"resultCount": 0, "results": []}),
    }
    outcome, seen = await probe("app_store", routes, target(app_store=["1232780281"]))
    assert outcome.state == "none" and [r.url.path for r in seen] == ["/lookup", "/search"]


@pytest.mark.parametrize(
    ("answer", "state"), [(timeout, "error"), ((200, "not json"), "error"), ((404, ""), "none"), ((403, ""), "skipped")]
)
async def test_app_store_failures(answer: Any, state: str) -> None:
    outcome, _ = await probe("app_store", {"https://itunes.apple.com/search": answer})
    assert outcome.state == state and outcome.value is None


# ---- targets and the per-startup run ----------------------------------------------------------------------


def test_targets_from_business_rows() -> None:
    row = {
        "id": "b-9",
        "name": "TallyHQ",
        "website": f"{SITE}/",
        "web_domain": "tallyhq-nlead.io",
        "country": "in",
        "extra": {
            "crawl": {
                "final_url": "https://www.tallyhq-nlead.io/",
                "profiles": {"github": ["tallyhq-nlead"], "app_store": ["6447000001", "x"]},
            }
        },
    }
    t = pr.target_of(row)
    assert t is not None and t.host == "www.tallyhq-nlead.io" and t.domain == "tallyhq-nlead.io"
    assert t.github == ["tallyhq-nlead"] and t.app_store == ["6447000001"]
    hosted = pr.target_of(
        {**row, "web_domain": "lovable.app", "extra": {"crawl": {"final_url": "https://tally.lovable.app/"}}}
    )
    assert hosted is not None and hosted.domain is None and hosted.platform_hosted
    assert pr.target_of({**row, "website": "not a url", "extra": {}}) is None


async def test_a_site_on_a_shared_host_skips_the_domain_probes() -> None:
    hosted = target(host="tally.webflow.io", domain=None)
    for name in ("domain_created", "first_cert", "dns", "app_links"):
        outcome, seen = await probe(name, {}, hosted)
        assert outcome.state == "none" and seen == []


async def test_the_per_startup_run_chains_app_links_into_the_app_store() -> None:
    routes = {
        f"{SITE}/robots.txt": (404, ""),
        AASA: (200, raw("aasa.json")),
        ASSETLINKS: (404, ""),
        "https://itunes.apple.com/lookup": (200, fixture("itunes_lookup.json")),
    }
    transport, seen = mock_transport(routes)
    async with pr.Probes(transport=transport, resolver=FakeResolver({})) as p:
        for http in (p.sites, p.itunes):
            http.min_gap = 0.0
        out = await p.probe(target(name="Notion"), {"app_store"}, lambda: 60.0)
    assert set(out) == {"app_links", "app_store"}
    assert out["app_store"].state == "ok"
    assert any(r.url.params.get("bundleId") == "so.notion.NotionAI.Prod" for r in seen)


async def test_probes_still_waiting_when_time_runs_out_are_left_out() -> None:
    resolver = FakeResolver({}, delay=5.0)
    transport, _ = mock_transport({})
    loop = asyncio.get_running_loop()
    end = loop.time() + 0.2
    async with pr.Probes(transport=transport, resolver=resolver) as p:
        out = await p.probe(target(), {"dns"}, lambda: end - loop.time())
        assert out == {}
        assert await p.probe(target(), {"dns", "github"}, lambda: 0.0) == {}
