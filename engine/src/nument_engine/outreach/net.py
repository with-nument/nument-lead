"""The only HTTP clients the outreach package opens: the Gmail API, Google OAuth and the email verifiers.

Scraping goes through http.PoliteClient; these are authenticated API calls, so they get their own small clients
with three guarantees (tests/test_outreach_hosts.py):
- every request is checked against `allowed_hosts` in config/outreach.yaml before it leaves (HostNotAllowed);
- proxy environment variables are ignored (trust_env=False), and only https is used;
- requests carry our user agent and a bounded timeout.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import httpx

from ..segments import load_yaml_config
from ..settings import get_settings

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class HostNotAllowed(RuntimeError):
    """An outreach client tried to call a host that config/outreach.yaml does not allow."""


@cache
def outreach_config() -> dict[str, Any]:
    """config/outreach.yaml (countries, windows, warm-up, auto-send bar, allowed hosts)."""
    return load_yaml_config("outreach", get_settings().config_dir)


def allowed_hosts() -> frozenset[str]:
    return frozenset(str(h).lower() for h in outreach_config().get("allowed_hosts", []))


def check_url(url: httpx.URL | str) -> None:
    """Raise HostNotAllowed unless the URL is https on an allowed host."""
    parsed = httpx.URL(str(url))
    host = (parsed.host or "").lower()
    if parsed.scheme != "https" or host not in allowed_hosts():
        raise HostNotAllowed(f"outreach clients may not call {parsed.scheme}://{host}")


def _guard(request: httpx.Request) -> None:
    check_url(request.url)


async def _aguard(request: httpx.Request) -> None:
    check_url(request.url)


def _headers() -> dict[str, str]:
    return {"user-agent": get_settings().user_agent}


def api_client(*, transport: httpx.BaseTransport | None = None, timeout: httpx.Timeout = TIMEOUT) -> httpx.Client:
    """A synchronous client for the outreach APIs. Use as `with api_client() as client:`."""
    return httpx.Client(
        timeout=timeout,
        trust_env=False,
        headers=_headers(),
        event_hooks={"request": [_guard]},
        transport=transport,
    )


def async_api_client(
    *, transport: httpx.AsyncBaseTransport | None = None, timeout: httpx.Timeout = TIMEOUT
) -> httpx.AsyncClient:
    """An async client for the outreach APIs. Use as `async with async_api_client() as client:`."""
    return httpx.AsyncClient(
        timeout=timeout,
        trust_env=False,
        headers=_headers(),
        event_hooks={"request": [_aguard]},
        transport=transport,
    )
