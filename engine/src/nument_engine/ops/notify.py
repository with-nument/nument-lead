"""Optional email alerts and reports (Steps 14.7 and 16.6.3).

Sent only when `ALERT_EMAIL` and `RESEND_API_KEY` are both set; otherwise every call is a quiet no-op. The
email goes to the founder (admin), so it may carry money numbers; caller-facing text never comes here.
`GITHUB_STEP_SUMMARY`, when present (GitHub Actions), receives the same markdown.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from ..logging import get_logger
from ..settings import get_settings

log = get_logger()

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_SENDER = "Nument Leads <onboarding@resend.dev>"
TIMEOUT_S = 20.0


def email_configured() -> bool:
    s = get_settings()
    return bool(s.alert_email and s.resend_api_key)


def send_email(subject: str, markdown: str) -> bool:
    """Send a plain-text email through Resend. Returns False (and logs) instead of raising: alerts never break a run."""
    s = get_settings()
    if not (s.alert_email and s.resend_api_key):
        return False
    sender = s.alert_email_from.strip() or DEFAULT_SENDER  # an empty ALERT_EMAIL_FROM means the default
    payload = {"from": sender, "to": [s.alert_email], "subject": subject, "text": markdown}
    headers = {"Authorization": f"Bearer {s.resend_api_key.get_secret_value()}", "User-Agent": s.user_agent}
    try:
        with httpx.Client(timeout=TIMEOUT_S, trust_env=False) as client:
            response = client.post(RESEND_URL, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("notify.email_failed", error=type(exc).__name__)
        return False
    log.info("notify.email_sent", subject=subject)
    return True


def step_summary(markdown: str) -> bool:
    """Append markdown to the GitHub Actions job summary, if this runs inside a workflow."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(markdown.rstrip() + "\n\n")
    return True
