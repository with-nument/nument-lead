"""Email delivery through Resend's HTTP API, and the GitHub job summary.

Who gets what: `notify_recipients` rows that are active and opted into the kind (morning list, alerts, weekly
report), managed by admins on Settings > Email recipients. While the table has no rows, or cannot be read (an
alert about a broken database must still go out), the engine falls back to `ALERT_EMAIL`.

Every recipient gets their own email: one API call per address, so nobody sees anyone else's address.
Without `RESEND_API_KEY` nothing is sent and nothing is called. Sending never raises: an email problem is
logged and never breaks a run. Money (spend, money won) goes only to recipients who are admins in the app,
or to the `ALERT_EMAIL` fallback (the founder).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, get_args

import httpx

from .. import db
from ..logging import get_logger
from ..settings import get_settings

log = get_logger()

RESEND_URL: Final = "https://api.resend.com/emails"
DEFAULT_SENDER: Final = "Nument Leads <leads@nument.in>"
TIMEOUT_S: Final = 20.0

Kind = Literal["morning", "alerts", "weekly"]
KINDS: Final[tuple[str, ...]] = get_args(Kind)

RECIPIENTS_SQL: Final = """
select email, coalesce(name, '') as name, morning, alerts, weekly, active
from public.notify_recipients
order by created_at, email
"""
# Admins in the app see money; everyone else gets the same emails without it.
ADMIN_EMAILS_SQL: Final = """
select lower(u.email) as email
from auth.users u join public.profiles p on p.user_id = u.id
where p.role = 'admin' and u.email is not null
"""


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str = ""
    admin: bool = False  # sees money: today's spend, the cap, money won


@dataclass(frozen=True)
class Email:
    subject: str
    html: str
    text: str


def email_configured() -> bool:
    """True when emails can be sent at all (the Resend key is set)."""
    return bool(get_settings().resend_api_key)


def _fallback() -> list[Recipient]:
    address = (get_settings().alert_email or "").strip().lower()
    return [Recipient(address, admin=True)] if address else []


def _admin_emails() -> set[str]:
    try:
        return {r["email"] for r in db.fetch_all(ADMIN_EMAILS_SQL)}
    except Exception as exc:  # no access to auth.users: nobody counts as admin except the fallback
        log.warning("notify.admins_unknown", error=type(exc).__name__)
        return set()


def recipients(kind: Kind) -> list[Recipient]:
    """Active recipients opted into `kind`, or ALERT_EMAIL while the list is empty or unreadable."""
    if kind not in KINDS:
        raise ValueError(f"unknown email kind {kind!r}")
    try:
        rows = db.fetch_all(RECIPIENTS_SQL)
    except Exception as exc:  # the database is down or the table is missing: alerts still reach the founder
        log.warning("notify.recipients_unreadable", error=type(exc).__name__)
        return _fallback()
    if not rows:
        return _fallback()
    admins = _admin_emails()
    fallback = (get_settings().alert_email or "").strip().lower()
    return [
        Recipient(r["email"], r["name"], admin=r["email"] in admins or r["email"] == fallback)
        for r in rows
        if r["active"] and r[kind]
    ]


def _payload(email: Email, to: str) -> dict[str, Any]:
    s = get_settings()
    payload: dict[str, Any] = {
        "from": s.alert_email_from.strip() or DEFAULT_SENDER,  # an empty ALERT_EMAIL_FROM means the default
        "to": [to],  # always exactly one address
        "subject": email.subject,
        "html": email.html,
        "text": email.text,
    }
    if s.alert_reply_to.strip():
        payload["reply_to"] = s.alert_reply_to.strip()
    return payload


def send(email: Email, to: Sequence[Recipient | str]) -> int:
    """Send `email` to each address separately. Returns how many were accepted; 0 without a key."""
    s = get_settings()
    if not s.resend_api_key or not to:
        return 0
    headers = {"Authorization": f"Bearer {s.resend_api_key.get_secret_value()}", "User-Agent": s.user_agent}
    sent = 0
    with httpx.Client(timeout=TIMEOUT_S, trust_env=False) as client:
        for r in to:
            address = r.email if isinstance(r, Recipient) else r
            try:
                response = client.post(RESEND_URL, json=_payload(email, address), headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                log.warning("notify.email_failed", error=type(exc).__name__, status=status)
                continue
            sent += 1
    log.info("notify.email_sent", subject=email.subject, sent=sent, of=len(to))
    return sent


def step_summary(markdown: str) -> bool:
    """Append markdown to the GitHub Actions job summary, if this runs inside a workflow."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(markdown.rstrip() + "\n\n")
    return True
