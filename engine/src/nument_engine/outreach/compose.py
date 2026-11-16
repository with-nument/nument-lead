"""What an outgoing email looks like when it leaves, and the content rules checked right before it does.

Contract 4.6 (lane E5a). The stored body never carries the footer: it is added here at send time, so every
email has `Team Nument`, the postal address (settings `outreach.postal_address`) and one plain opt-out line
with the unsubscribe link `{APP_URL}/u/{thread_id}`. No footer, no send.

Rules every outgoing email passes here, whatever an earlier stage did:
- no `{...}` placeholder (and no `[First name]` style one) is left in the subject or body;
- the first email (day 0) carries no link of any kind;
- follow-ups reply in the same conversation with `Re: <day 0 subject>`;
- in dev every recipient is replaced by settings `outreach.sandbox_to`, and without it nothing is sent.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

RFC_ID_DOMAIN: Final = "nument.in"
SIGNATURE: Final = "Team Nument"
OPT_OUT_LINE: Final = "If you'd rather not hear from us, you can opt out here: {url}"
UNSUBSCRIBE_SUBJECT: Final = "unsubscribe"

# A placeholder an AI writer or a template left behind: {plan_link}, {{name}}, [First Name], [Company].
PLACEHOLDER: Final = re.compile(
    r"\{[^{}\n]{0,60}\}"
    r"|\[\s*(?:first[ _]?name|last[ _]?name|full[ _]?name|name|company(?:[ _]?name)?|your[ _]?name|founder"
    r"(?:[ _]?name)?|product(?:[ _]?name)?|city|link|url|date|time|plan[ _]?link|case[ _]?study)\s*\]",
    re.I,
)
# A link in the text: a scheme, www., or a bare domain with a common ending (gmail turns those into links).
# An email address is not a link here; the address part before the @ is skipped.
_TLDS: Final = (
    "com|net|org|io|ai|co|app|dev|in|me|so|to|xyz|tech|site|online|store|shop|link|page|ly|gl|gg|us|uk|ae|sg|au|"
    "ca|nz|de|fr|nl|ie|be|se|fi|pt|br|mx|ph|my|id|info|biz|cloud|studio|digital|agency|design|world|life"
)
LINK: Final = re.compile(
    r"https?://|\bwww\.|(?<![@\w.-])(?:[a-z0-9-]+\.)+(?:" + _TLDS + r")(?:/[^\s]*)?(?![\w@-])",
    re.I,
)
_REPLY_PREFIX: Final = re.compile(r"^\s*(?:re|aw|sv|antw)\s*(?:\[\d+\])?\s*:", re.I)
_EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ComposeError(ValueError):
    """The email cannot go out as it is; `reason` is a short machine name for the run stats."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Composed:
    """The final text and headers of one outgoing email."""

    to: str
    subject: str
    body: str  # with the footer
    unsubscribe_url: str
    unsubscribe_mailto: str
    sandboxed: bool  # the real recipient was replaced by the sandbox address


def new_rfc_message_id() -> str:
    """A fresh RFC 5322 Message-ID, generated before sending so a crash can be recovered by searching for it."""
    return f"<{uuid.uuid4()}@{RFC_ID_DOMAIN}>"


def placeholders(text: str) -> list[str]:
    """Placeholders left in the text, in order."""
    return [m.group(0) for m in PLACEHOLDER.finditer(text or "")]


def links(text: str) -> list[str]:
    """Links in the text: URLs, www. addresses and bare domains such as nument.in."""
    return [m.group(0) for m in LINK.finditer(text or "")]


def reply_subject(subject: str) -> str:
    """`Re: <subject>`, without stacking a second `Re:` on a subject that already has one."""
    clean = " ".join((subject or "").split())
    if not clean:
        raise ComposeError("no_subject", "a reply needs the subject of the conversation")
    return clean if _REPLY_PREFIX.match(clean) else f"Re: {clean}"


def unsubscribe_url(app_url: str, thread_id: str) -> str:
    """The one-click opt-out page for this conversation (the web app marks it done and suppresses the address)."""
    base = (app_url or "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise ComposeError("no_footer", "APP_URL must be an https address for the opt-out link")
    return f"{base}/u/{thread_id}"


def unsubscribe_mailto(mailbox: str) -> str:
    return f"mailto:{mailbox}?subject={UNSUBSCRIBE_SUBJECT}"


def footer(postal_address: str | None, opt_out_url: str) -> str:
    """Team Nument, the postal address and one plain opt-out line. Raises without a postal address."""
    lines = [" ".join(line.split()) for line in str(postal_address or "").splitlines()]
    address = ", ".join(line for line in lines if line)  # a multi-line address becomes one line
    if not address:
        raise ComposeError("no_footer", "settings outreach.postal_address is empty: no footer, no send")
    return f"{SIGNATURE}\n{address}\n{OPT_OUT_LINE.format(url=opt_out_url)}"


def has_footer(body: str, postal_address: str, opt_out_url: str) -> bool:
    """True when the body ends with the full footer (checked again on the final text before sending)."""
    return body.rstrip().endswith(footer(postal_address, opt_out_url))


def with_footer(body: str, postal_address: str | None, opt_out_url: str) -> str:
    """The body, a blank line, then the footer. Trailing spaces and blank lines are tidied."""
    text = "\n".join(line.rstrip() for line in (body or "").strip().splitlines())
    return f"{text}\n\n{footer(postal_address, opt_out_url)}\n"


def check_content(*, subject: str, body: str, step: int | None) -> None:
    """The content rules every outgoing email passes before its footer is added. Raises ComposeError."""
    if not (body or "").strip():
        raise ComposeError("empty_body", "the email has no text")
    if step == 0 and not (subject or "").strip():
        raise ComposeError("no_subject", "the first email has no subject")
    left = placeholders(subject) + placeholders(body)
    if left:
        raise ComposeError("placeholder", f"placeholder left in the email: {', '.join(left[:3])}")
    if step == 0:
        found = links(subject) + links(body)
        if found:
            raise ComposeError("link_in_day0", f"the first email must not carry a link: {', '.join(found[:3])}")


def recipient(to_email: str, *, production: bool, sandbox_to: str | None) -> tuple[str, bool]:
    """Who the email really goes to: the recipient in production; in dev, always the sandbox address.

    Returns (address, sandboxed). Raises ComposeError in dev without a sandbox address: nothing is sent then.
    """
    if production:
        address = (to_email or "").strip()
        if not _EMAIL.match(address):
            raise ComposeError("bad_address", "the recipient address is not valid")
        return address, False
    sandbox = str(sandbox_to or "").strip()
    if not _EMAIL.match(sandbox):
        raise ComposeError("no_sandbox", "dev sends only to settings outreach.sandbox_to, which is not set")
    return sandbox, True


def compose(
    *,
    thread_id: str,
    to_email: str,
    subject: str,
    body: str,
    step: int | None,
    mailbox: str,
    app_url: str,
    postal_address: str | None,
    production: bool,
    sandbox_to: str | None,
) -> Composed:
    """The email as it will leave: content checked, recipient decided, footer added and verified."""
    check_content(subject=subject, body=body, step=step)
    to, sandboxed = recipient(to_email, production=production, sandbox_to=sandbox_to)
    opt_out = unsubscribe_url(app_url, thread_id)
    final = with_footer(body, postal_address, opt_out)
    if not has_footer(final, str(postal_address), opt_out):
        raise ComposeError("no_footer", "the footer is missing from the final text")
    return Composed(
        to=to,
        subject=" ".join(subject.split()),
        body=final,
        unsubscribe_url=opt_out,
        unsubscribe_mailto=unsubscribe_mailto(mailbox),
        sandboxed=sandboxed,
    )


def country_codes(values: Iterable[Any]) -> frozenset[str]:
    """Two-letter country codes from config, lower case. YAML reads a bare `no` (Norway) as false and `yes` as
    true; both are turned back into their codes, so Norway stays blocked."""
    out: set[str] = set()
    for value in values or []:
        if isinstance(value, bool):
            out.add("no" if value is False else "yes")
        elif value is not None and str(value).strip():
            out.add(str(value).strip().lower())
    return frozenset(out)
