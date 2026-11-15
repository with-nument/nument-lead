"""Outreach clients call only their own hosts (Gmail API, Google OAuth, the email verifiers), never via a proxy."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from nument_engine.outreach import net

ENGINE = Path(__file__).resolve().parents[1]
OUTREACH = ENGINE / "src" / "nument_engine" / "outreach"

# Links written into emails or pages (the plan page, the unsubscribe page, the booking page): never fetched.
LINK_HOSTS = {"lead.nument.in", "nument.in", "cal.com"}


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def test_allowed_hosts_are_the_four_api_hosts() -> None:
    assert net.allowed_hosts() == {
        "gmail.googleapis.com",
        "oauth2.googleapis.com",
        "api.quickemailverification.com",
        "client.myemailverifier.com",
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        "https://oauth2.googleapis.com/token",
        "https://api.quickemailverification.com/v1/verify?email=x%40example.com",
        "https://client.myemailverifier.com/verifier/validate_single/x@example.com/KEY",
    ],
)
def test_allowed_hosts_pass(url: str) -> None:
    with net.api_client(transport=httpx.MockTransport(_ok)) as client:
        assert client.get(url).status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/collect",
        "http://gmail.googleapis.com/gmail/v1/users/me/messages",  # not https
        "https://gmail.googleapis.com.evil.example.com/x",  # look-alike
        "https://www.linkedin.com/in/someone",
    ],
)
def test_other_hosts_are_refused_before_any_request(url: str) -> None:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    with net.api_client(transport=httpx.MockTransport(record)) as client, pytest.raises(net.HostNotAllowed):
        client.get(url)
    assert seen == []


async def test_async_client_refuses_other_hosts() -> None:
    async with net.async_api_client(transport=httpx.MockTransport(_ok)) as client:
        assert (await client.get("https://oauth2.googleapis.com/token")).status_code == 200
        with pytest.raises(net.HostNotAllowed):
            await client.get("https://evil.example.com/")


def test_clients_ignore_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    with net.api_client() as client:
        assert client._trust_env is False and not client._mounts
        assert client.headers["user-agent"].startswith("NumentLeadBot")


def test_only_net_opens_clients_in_outreach() -> None:
    pattern = re.compile(
        r"httpx\.(?:Async)?Client\(|requests\.(?:get|post|Session)\(|urlopen\(|aiohttp\.ClientSession\(|smtplib\."
    )
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(OUTREACH.glob("*.py"))
        if path.name != "net.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line) and not line.lstrip().startswith("#")
    ]
    assert offenders == []


def test_url_literals_in_outreach_point_at_allowed_or_link_hosts() -> None:
    allowed = net.allowed_hosts() | LINK_HOSTS
    found = {
        (path.name, host.lower())
        for path in sorted(OUTREACH.glob("*.py"))
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", path.read_text(encoding="utf-8"))
    }
    assert {f for f in found if f[1] not in allowed} == set()
