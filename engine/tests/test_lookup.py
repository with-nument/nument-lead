"""Official websites for businesses born from a job post or an ask (the need-first track, 13 Nov 2026)."""

from __future__ import annotations

from types import SimpleNamespace

from nument_engine.pipeline import lookup

GROUNDING = {
    "sources": [
        {"uri": "https://vertexaisearch.example/redirect/1", "title": "brightcart.in"},
        {"uri": "https://www.naukri.com/job-1", "title": "naukri.com"},
    ],
    "supports": [{"text": "Brightcart Foods runs brightcart.in from Pune.", "chunks": [0]}],
}


def out(url: str | None) -> SimpleNamespace:
    return SimpleNamespace(website=url, website_line=f"Website: {url}")


def test_only_a_cited_own_website_is_a_candidate() -> None:
    assert lookup.candidate_url(out("brightcart.in"), GROUNDING) == "https://brightcart.in"
    assert lookup.candidate_url(out("https://www.naukri.com/job-1"), GROUNDING) is None  # a job board, never
    assert lookup.candidate_url(out("https://guessed-domain.in"), GROUNDING) is None  # the search never cited it
    assert lookup.candidate_url(out("unknown"), GROUNDING) is None
    assert lookup.candidate_url(out(None), GROUNDING) is None


def test_the_home_page_must_name_the_business() -> None:
    page = "<html><head><title>Brightcart | Fresh groceries in Pune</title></head><body>Order now</body></html>"
    assert lookup.page_matches("Brightcart Foods Pvt Ltd", page, "https://brightcart.in")
    other = "<html><head><title>Green Basket | Groceries</title></head><body>Order now</body></html>"
    assert not lookup.page_matches("Brightcart Foods Pvt Ltd", other, "https://greenbasket.in")
    by_domain = "<html><head><title>Home</title></head><body>Welcome</body></html>"
    assert lookup.page_matches("Brightcart Foods", by_domain, "https://brightcart.in")
