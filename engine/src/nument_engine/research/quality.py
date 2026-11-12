"""Mobile speed score from the PageSpeed Insights API v5 (Step 9.9).

Runs in the morning for the best businesses only (about 100 a day), 4 at a time, because each call takes 15 to
40 seconds. Needs `GOOGLE_MAPS_API_KEY` with the PageSpeed Insights API enabled; without it nothing runs. Each
call is logged in `costs` (provider `pagespeed`, free) so the daily cap can be counted.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..http import PoliteClient
from ..settings import get_settings

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
TIMEOUT = httpx.Timeout(90.0, connect=10.0)
SLOW_SITE_BELOW = 40  # Step 7.5.7: a mobile performance score under 40 is a slow_site signal


def api_key() -> str:
    key = get_settings().google_maps_api_key
    return key.get_secret_value() if key else ""


def score_from(data: dict[str, Any]) -> int | None:
    """`lighthouseResult.categories.performance.score` x 100, or None when the report has no score."""
    try:
        score = data["lighthouseResult"]["categories"]["performance"]["score"]
    except (KeyError, TypeError):
        return None
    if score is None:
        return None
    return round(float(score) * 100)


async def mobile_score(client: PoliteClient, url: str, key: str) -> tuple[int | None, str]:
    """(score, problem). A quota error or a page Lighthouse cannot load gives (None, reason)."""
    params = {"url": url, "strategy": "mobile", "category": "performance", "key": key}
    res = await client.get(API, params=params, check_robots=False, raise_on_block=False)
    if res.status == 200:
        try:
            return score_from(res.json()), ""
        except ValueError:
            return None, "bad json"
    if res.status == 429:
        return None, "quota"
    return None, f"{res.state} {res.status}"
