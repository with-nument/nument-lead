"""The real Gmail client against a mock Gmail API: tokens, MIME, sending, crash recovery, reading mail (E5a).

No request leaves the machine: every test runs on httpx.MockTransport. Message fixtures (bounces, replies,
booking invites) are in tests/fixtures/e5a, written from the RFC 3464 and Gmail formats with example addresses.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs

import httpx
import pytest

from nument_engine.outreach import gmail as g

FIXTURES = Path(__file__).parent / "fixtures" / "e5a"
ME = "hello.nument@gmail.com"
OUR_ID = "<3f0e8f7e-1b2a-4c5d-9e8f-0a1b2c3d4e5f@nument.in>"


def raw_of(name: str) -> str:
    return base64.urlsafe_b64encode((FIXTURES / name).read_bytes()).decode().rstrip("=")


@dataclass
class FakeGmail:
    """Just enough of the Gmail API and the OAuth token endpoint, with switches for failures."""

    token_answers: list[httpx.Response] = field(default_factory=list)
    send_answers: list[httpx.Response | Exception] = field(default_factory=list)
    sent_message_id: str | None = None  # what Gmail reports as the Message-ID of a sent message (None = ours)
    raw_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)  # query -> ids
    history_pages: list[dict[str, Any]] | httpx.Response | None = None
    profile_email: str = ME
    requests: list[httpx.Request] = field(default_factory=list)
    sent_raw: list[bytes] = field(default_factory=list)
    tokens_issued: int = 0
    unauthorized_once: bool = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.host == "oauth2.googleapis.com":
            if self.token_answers:
                return self.token_answers.pop(0)
            self.tokens_issued += 1
            return httpx.Response(200, json={"access_token": f"ya29.t{self.tokens_issued}", "expires_in": 3599})
        assert url.host == "gmail.googleapis.com"
        if self.unauthorized_once:
            self.unauthorized_once = False
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
        path = url.path.removeprefix("/gmail/v1/users/me/")
        params = parse_qs(url.query.decode())
        if path == "profile":
            return httpx.Response(200, json={"emailAddress": self.profile_email, "historyId": "9000"})
        if path == "messages/send":
            if self.send_answers:
                answer = self.send_answers.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer
            body = json.loads(request.content)
            raw = base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4))
            self.sent_raw.append(raw)
            n = len(self.sent_raw)
            mime = BytesParser(policy=policy.default).parsebytes(raw)
            self.meta_by_id[f"s{n}"] = {
                "id": f"s{n}",
                "threadId": body.get("threadId") or f"th{n}",
                "labelIds": ["SENT"],
                "internalDate": "1794830400000",  # 2026-11-16 12:00:00 UTC
                "payload": {"headers": [{"name": "Message-ID", "value": self.sent_message_id or mime["Message-ID"]}]},
            }
            return httpx.Response(200, json={"id": f"s{n}", "threadId": body.get("threadId") or f"th{n}"})
        if path == "messages":
            query = params.get("q", [""])[0]
            ids = self.lists.get(query, [])
            return httpx.Response(200, json={"messages": [{"id": i, "threadId": "x"} for i in ids]} if ids else {})
        if path == "history":
            if isinstance(self.history_pages, httpx.Response):
                return self.history_pages
            pages = self.history_pages or [{"historyId": "9001"}]
            token = params.get("pageToken", [None])[0]
            return httpx.Response(200, json=pages[int(token) if token else 0])
        if path.startswith("messages/") and path.endswith("/modify"):
            return httpx.Response(200, json={"id": path.split("/")[1]})
        if path.startswith("messages/"):
            gmail_id = path.split("/")[1]
            fmt = params.get("format", ["full"])[0]
            source = self.raw_by_id if fmt == "raw" else self.meta_by_id
            if gmail_id not in source:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Requested entity was not found."}})
            return httpx.Response(200, json=source[gmail_id])
        return httpx.Response(400, json={"error": {"code": 400, "message": f"unexpected {path}"}})


@pytest.fixture
def fake() -> FakeGmail:
    return FakeGmail()


@pytest.fixture
def mailbox(fake: FakeGmail) -> g.GmailMailbox:
    return g.GmailMailbox(
        ME,
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="1//refresh-token",
        transport=httpx.MockTransport(fake.handler),
        sleep=lambda _s: None,
    )


def outgoing(**overrides: Any) -> g.Outgoing:
    values: dict[str, Any] = {
        "to": "maya@acme.example.com",
        "subject": "Quick question about Acme",
        "body": "Hi Maya,\n\nSaw your launch. Who builds the app today?\n\nTeam Nument\n",
        "rfc_message_id": OUR_ID,
        "unsubscribe_url": "https://lead.nument.in/u/thread-1",
        "unsubscribe_mailto": f"mailto:{ME}?subject=unsubscribe",
    }
    values.update(overrides)
    return g.Outgoing(**values)


def parsed(mime: bytes) -> EmailMessage:
    return cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(mime))


def text_of(msg: EmailMessage) -> str:
    """The body as written: the wire format uses CRLF line endings."""
    return str(msg.get_content()).replace("\r\n", "\n")


# ---------------------------------------------------------------------------
# MIME
# ---------------------------------------------------------------------------


def test_mime_is_plain_utf8_with_our_headers() -> None:
    msg = parsed(g.build_mime(outgoing(body="Café talk, naïve ideas.\n"), ME))
    assert msg["From"] == f"Nument <{ME}>"
    assert msg["To"] == "maya@acme.example.com"
    assert msg["Message-ID"] == OUR_ID
    assert msg[g.REF_HEADER] == OUR_ID
    assert msg.get_content_type() == "text/plain" and msg.get_content_charset() == "utf-8"
    assert msg["Content-Transfer-Encoding"] == "quoted-printable"
    assert text_of(msg) == "Café talk, naïve ideas.\n"
    assert msg["List-Unsubscribe"] == f"<https://lead.nument.in/u/thread-1>, <mailto:{ME}?subject=unsubscribe>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "In-Reply-To" not in msg and "References" not in msg
    assert msg["Date"]


def test_mime_threading_headers_for_a_follow_up() -> None:
    first, second = "<a@nument.in>", "<b@nument.in>"
    msg = parsed(
        g.build_mime(outgoing(subject="Re: Quick question", in_reply_to=second, references=(first, second)), ME)
    )
    assert msg["In-Reply-To"] == second
    assert msg["References"] == f"{first} {second}"
    assert msg["Subject"] == "Re: Quick question"
    # the previous message is always in References, even when the caller forgot it
    alone = parsed(g.build_mime(outgoing(in_reply_to=second), ME))
    assert alone["References"] == second


def test_non_ascii_subject_is_encoded_on_the_wire() -> None:
    mime = g.build_mime(outgoing(subject="Idée rapide pour Café"), ME)
    head = mime.split(b"\r\n\r\n", 1)[0]
    assert b"=?utf-8?" in head.lower() and "Idée".encode() not in head
    assert parsed(mime)["Subject"] == "Idée rapide pour Café"


@pytest.mark.parametrize("field_name", ["to", "subject", "rfc_message_id"])
def test_header_injection_is_refused(field_name: str) -> None:
    with pytest.raises(g.MailboxError) as err:
        g.build_mime(outgoing(**{field_name: "x@example.com\r\nBcc: victim@example.com"}), ME)
    assert err.value.kind == "invalid"


def test_long_body_lines_survive() -> None:
    body = "word " * 400 + "\n"
    assert text_of(parsed(g.build_mime(outgoing(body=body), ME))) == body


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_token_refresh_sends_the_oauth_form_and_is_cached(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    assert mailbox.access_token() == "ya29.t1"
    assert mailbox.access_token() == "ya29.t1"  # cached in memory
    token_requests = [r for r in fake.requests if r.url.host == "oauth2.googleapis.com"]
    assert len(token_requests) == 1
    form = parse_qs(token_requests[0].content.decode())
    assert form == {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "refresh_token": ["1//refresh-token"],
        "grant_type": ["refresh_token"],
    }
    assert str(token_requests[0].url) == g.TOKEN_URL
    assert "refresh" not in repr(mailbox) and "secret" not in repr(mailbox)


def test_an_expired_token_is_refreshed(fake: FakeGmail) -> None:
    now = [0.0]
    box = g.GmailMailbox(
        ME,
        client_id="c",
        client_secret="s",
        refresh_token="r",
        transport=httpx.MockTransport(fake.handler),
        clock=lambda: now[0],
    )
    assert box.access_token() == "ya29.t1"
    now[0] = 3599 - g.TOKEN_MARGIN_S - 1
    assert box.access_token() == "ya29.t1"
    now[0] = 3599 - g.TOKEN_MARGIN_S + 1
    assert box.access_token() == "ya29.t2"


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}, "auth"),
        (401, {"error": "invalid_client", "error_description": "Unauthorized"}, "auth"),
        (429, {"error": "rate_limit_exceeded"}, "rate_limit"),
        (503, {"error": "backend"}, "transient"),
    ],
)
def test_token_errors(fake: FakeGmail, mailbox: g.GmailMailbox, status: int, body: dict[str, str], kind: str) -> None:
    fake.token_answers = [httpx.Response(status, json=body)]
    with pytest.raises(g.MailboxError) as err:
        mailbox.access_token()
    assert err.value.kind == kind and err.value.status == status
    assert "refresh-token" not in str(err.value) and "client-secret" not in str(err.value)


def test_token_answer_without_a_token_is_an_auth_error(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.token_answers = [httpx.Response(200, json={"expires_in": 3599})]
    with pytest.raises(g.MailboxError) as err:
        mailbox.access_token()
    assert err.value.kind == "auth"


def test_token_network_failure_is_transient() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    box = g.GmailMailbox(ME, client_id="c", client_secret="s", refresh_token="r", transport=httpx.MockTransport(down))
    with pytest.raises(g.MailboxError) as err:
        box.access_token()
    assert err.value.kind == "transient"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def test_send_posts_raw_and_reads_back_the_message_id(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    sent = mailbox.send(outgoing())
    assert sent.gmail_message_id == "s1" and sent.gmail_thread_id == "th1"
    assert sent.rfc_message_id == OUR_ID
    assert sent.sent_at.isoformat() == "2026-11-16T12:00:00+00:00"
    msg = parsed(fake.sent_raw[0])
    assert msg["Message-ID"] == OUR_ID and msg["To"] == "maya@acme.example.com"
    send_request = next(r for r in fake.requests if r.url.path.endswith("/messages/send"))
    assert send_request.headers["authorization"] == "Bearer ya29.t1"
    assert "threadId" not in json.loads(send_request.content)


def test_send_in_a_thread_passes_the_thread_id(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    sent = mailbox.send(outgoing(gmail_thread_id="th-existing", in_reply_to="<a@nument.in>"))
    send_request = next(r for r in fake.requests if r.url.path.endswith("/messages/send"))
    assert json.loads(send_request.content)["threadId"] == "th-existing"
    assert sent.gmail_thread_id == "th-existing"


def test_send_reports_the_message_id_gmail_really_used(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.sent_message_id = "<CAGbN7xq-replaced@mail.gmail.com>"
    assert mailbox.send(outgoing()).rfc_message_id == "<CAGbN7xq-replaced@mail.gmail.com>"


def test_send_refuses_a_token_for_another_address(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.profile_email = "someone.else@gmail.com"
    with pytest.raises(g.MailboxError) as err:
        mailbox.send(outgoing())
    assert err.value.kind == "auth" and not err.value.maybe_sent
    assert fake.sent_raw == []


def test_send_retries_once_after_401_with_a_new_token(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    mailbox.access_token()
    fake.unauthorized_once = True
    assert mailbox.send(outgoing()).gmail_message_id == "s1"
    assert fake.tokens_issued == 2 and len(fake.sent_raw) == 1


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [
        (429, None, "rate_limit"),
        (403, "userRateLimitExceeded", "rate_limit"),
        (403, "rateLimitExceeded", "rate_limit"),
        (403, "dailyLimitExceeded", "quota"),
        (403, "domainPolicy", "auth"),
        (403, "insufficientPermissions", "auth"),
        (400, "invalidArgument", "invalid"),
    ],
)
def test_send_refusals_map_to_kinds_and_are_definitely_not_sent(
    fake: FakeGmail, mailbox: g.GmailMailbox, status: int, reason: str | None, kind: str
) -> None:
    errors = [{"domain": "usageLimits", "reason": reason, "message": "x"}] if reason else []
    fake.send_answers = [httpx.Response(status, json={"error": {"code": status, "message": "no", "errors": errors}})]
    with pytest.raises(g.MailboxError) as err:
        mailbox.send(outgoing())
    assert err.value.kind == kind and err.value.status == status and not err.value.maybe_sent


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500, json={"error": {"code": 500, "message": "Backend Error"}}),
        httpx.Response(503, text="unavailable"),
        httpx.ReadTimeout("timed out"),
        httpx.RemoteProtocolError("connection closed"),
    ],
)
def test_unclear_send_failures_are_never_retried(
    fake: FakeGmail, mailbox: g.GmailMailbox, answer: httpx.Response | Exception
) -> None:
    fake.send_answers = [answer, httpx.Response(200, json={"id": "should-not-happen", "threadId": "t"})]
    with pytest.raises(g.MailboxError) as err:
        mailbox.send(outgoing())
    assert err.value.kind == "transient" and err.value.maybe_sent
    sends = [r for r in fake.requests if r.url.path.endswith("/messages/send")]
    assert len(sends) == 1


def test_a_connection_that_never_opened_is_retried(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.send_answers = [httpx.ConnectError("refused")]
    assert mailbox.send(outgoing()).gmail_message_id == "s1"


def test_send_succeeds_even_when_the_read_back_fails(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    original = fake.handler

    def no_metadata(request: httpx.Request) -> httpx.Response:
        if "format=metadata" in str(request.url):
            return httpx.Response(500, json={"error": {"code": 500, "message": "Backend Error"}})
        return original(request)

    box = g.GmailMailbox(
        ME,
        client_id="c",
        client_secret="s",
        refresh_token="r",
        transport=httpx.MockTransport(no_metadata),
        sleep=lambda _s: None,
    )
    sent = box.send(outgoing())
    assert sent.gmail_message_id == "s1" and sent.rfc_message_id == OUR_ID


def test_all_requests_go_to_allowed_hosts_only(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    mailbox.send(outgoing())
    assert {r.url.host for r in fake.requests} <= {"gmail.googleapis.com", "oauth2.googleapis.com"}
    assert all(r.url.scheme == "https" for r in fake.requests)


# ---------------------------------------------------------------------------
# Crash recovery: find_sent
# ---------------------------------------------------------------------------


def _sent_meta(gmail_id: str, headers: dict[str, str], labels: tuple[str, ...] = ("SENT",)) -> dict[str, Any]:
    return {
        "id": gmail_id,
        "threadId": f"th-{gmail_id}",
        "labelIds": list(labels),
        "internalDate": "1794830400000",
        "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]},
    }


def test_find_sent_by_message_id_search(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    bare = OUR_ID.strip("<>")
    fake.lists[f"rfc822msgid:{bare}"] = ["s9"]
    fake.meta_by_id["s9"] = _sent_meta("s9", {"Message-ID": OUR_ID})
    found = mailbox.find_sent(OUR_ID)
    assert found is not None and found.gmail_message_id == "s9" and found.gmail_thread_id == "th-s9"
    assert found.rfc_message_id == OUR_ID


def test_find_sent_when_gmail_replaced_the_message_id(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.lists["from:me to:maya@acme.example.com newer_than:14d"] = ["s7", "s8"]
    fake.meta_by_id["s7"] = _sent_meta("s7", {"Message-ID": "<other@mail.gmail.com>"})
    fake.meta_by_id["s8"] = _sent_meta(
        "s8", {"Message-ID": "<CA-new@mail.gmail.com>", g.ORIGINAL_ID_HEADER: OUR_ID, g.REF_HEADER: OUR_ID}
    )
    found = mailbox.find_sent(OUR_ID, to="maya@acme.example.com")
    assert found is not None and found.gmail_message_id == "s8"
    assert found.rfc_message_id == "<CA-new@mail.gmail.com>"


def test_find_sent_scans_recent_mail_without_a_recipient(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.lists["from:me newer_than:7d"] = ["s5"]
    fake.meta_by_id["s5"] = _sent_meta("s5", {"Message-ID": "<CA-x@mail.gmail.com>", g.REF_HEADER: OUR_ID})
    found = mailbox.find_sent(OUR_ID)
    assert found is not None and found.gmail_message_id == "s5"


def test_find_sent_ignores_a_received_copy(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.lists[f"rfc822msgid:{OUR_ID.strip('<>')}"] = ["in1"]
    fake.meta_by_id["in1"] = _sent_meta("in1", {"Message-ID": OUR_ID}, labels=("INBOX",))
    assert mailbox.find_sent(OUR_ID) is None


def test_find_sent_nothing(mailbox: g.GmailMailbox) -> None:
    assert mailbox.find_sent(OUR_ID, to="maya@acme.example.com") is None


# ---------------------------------------------------------------------------
# Reading mail: fetch_new and the message parser
# ---------------------------------------------------------------------------


def _raw(gmail_id: str, fixture: str, labels: tuple[str, ...] = ("INBOX", "UNREAD")) -> dict[str, Any]:
    return {
        "id": gmail_id,
        "threadId": f"th-{gmail_id}",
        "labelIds": list(labels),
        "internalDate": "1794843000000",
        "raw": raw_of(fixture),
    }


def test_parse_a_plain_reply() -> None:
    msg = g.parse_message(_raw("r1", "reply_plain.eml"))
    assert msg.from_email == "maya@acme.example.com" and msg.from_name == "Maïa Schön"
    assert msg.subject == f"Re: Quick question about Acme {chr(0x2014)} café"  # an em dash
    assert msg.rfc_message_id == "<CAmaya-reply-001@mail.acme.example.com>"
    assert msg.in_reply_to == OUR_ID
    assert msg.body_text.startswith("Hi,\n\nYes, send me the plan. We meet at the café on Tuesday.")
    assert not msg.is_bounce and msg.bounced_rfc_id is None and msg.calendar_ics is None
    assert msg.labels == ("INBOX", "UNREAD")
    assert msg.received_at.isoformat() == "2026-11-16T15:30:00+00:00"
    assert msg.gmail_message_id == "r1" and msg.gmail_thread_id == "th-r1"


def test_parse_an_html_only_reply() -> None:
    msg = g.parse_message(_raw("r2", "reply_html.eml"))
    assert msg.body_text == "Not right now,\nmaybe next quarter.\nLee"
    assert msg.in_reply_to == "<11111111-2222-3333-4444-555555555555@nument.in>"


def test_gmail_bounce_reads_the_original_message_id() -> None:
    msg = g.parse_message(_raw("b1", "bounce_gmail.eml"))
    assert msg.is_bounce
    assert msg.bounced_rfc_id == OUR_ID  # from the attached original, not the bounce's own References
    assert msg.from_email == "mailer-daemon@googlemail.com"
    assert "Address not found" in msg.body_text


def test_bounce_with_returned_headers_only() -> None:
    msg = g.parse_message(_raw("b2", "bounce_headers_only.eml"))
    assert msg.is_bounce and msg.bounced_rfc_id == "<CAGbN7xq-replaced-by-gmail@mail.gmail.com>"


def test_bounce_without_a_report_part() -> None:
    msg = g.parse_message(_raw("b3", "bounce_text_only.eml"))
    assert msg.is_bounce and msg.bounced_rfc_id == "<7e7e7e7e-aaaa-bbbb-cccc-ddddeeeeffff@nument.in>"


def test_a_delay_notice_is_not_a_bounce() -> None:
    msg = g.parse_message(_raw("d1", "delay_dsn.eml"))
    assert not msg.is_bounce and msg.bounced_rfc_id is None


def test_calendar_invite_text() -> None:
    msg = g.parse_message(_raw("c1", "calcom_booking.eml"))
    assert msg.calendar_ics is not None and msg.calendar_ics.startswith("BEGIN:VCALENDAR")
    assert "ATTENDEE;CN=Maya" in msg.calendar_ics
    assert msg.body_text.startswith("A new event has been scheduled")


def test_calendar_invite_as_an_ics_attachment() -> None:
    msg = g.parse_message(_raw("c2", "ics_attachment.eml"))
    assert msg.calendar_ics is not None and "UID:resched-456@cal.example.com" in msg.calendar_ics


def test_fetch_new_follows_history_pages_and_skips_our_own_mail(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.history_pages = [
        {
            "history": [
                {"id": "101", "messagesAdded": [{"message": {"id": "r1", "threadId": "th-r1"}}]},
                {"id": "102", "messagesAdded": [{"message": {"id": "own", "threadId": "t"}}]},
            ],
            "nextPageToken": "1",
            "historyId": "103",
        },
        {
            "history": [
                {"id": "104", "messagesAdded": [{"message": {"id": "b1", "threadId": "th-b1"}}]},
                {"id": "105", "messagesAdded": [{"message": {"id": "r1", "threadId": "th-r1"}}]},  # again
                {"id": "106", "messagesAdded": [{"message": {"id": "gone", "threadId": "t"}}]},
            ],
            "historyId": "107",
        },
    ]
    fake.raw_by_id = {
        "r1": _raw("r1", "reply_plain.eml"),
        "own": _raw("own", "reply_plain.eml", labels=("SENT",)),
        "b1": _raw("b1", "bounce_gmail.eml"),
    }
    messages, cursor = mailbox.fetch_new("100")
    assert [m.gmail_message_id for m in messages] == ["r1", "b1"]
    assert cursor == "107"
    history_calls = [r for r in fake.requests if r.url.path.endswith("/history")]
    first = parse_qs(history_calls[0].url.query.decode())
    assert first["startHistoryId"] == ["100"] and first["historyTypes"] == ["messageAdded"]


def test_fetch_new_without_changes_keeps_going(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.history_pages = [{"historyId": "555"}]
    assert mailbox.fetch_new("550") == ([], "555")


def test_fetch_new_first_time_reads_recent_mail(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.lists[g.FIRST_SYNC_QUERY] = ["r2", "r1"]  # newest first, as Gmail lists them
    fake.raw_by_id = {"r1": _raw("r1", "reply_plain.eml"), "r2": _raw("r2", "reply_html.eml")}
    messages, cursor = mailbox.fetch_new(None)
    assert [m.gmail_message_id for m in messages] == ["r1", "r2"]  # oldest first
    assert cursor == "9000"


def test_fetch_new_after_the_history_cursor_expired(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.history_pages = httpx.Response(
        404, json={"error": {"code": 404, "message": "Requested entity was not found."}}
    )
    fake.lists[g.RESYNC_QUERY] = ["b1"]
    fake.raw_by_id = {"b1": _raw("b1", "bounce_gmail.eml")}
    messages, cursor = mailbox.fetch_new("1")
    assert [m.gmail_message_id for m in messages] == ["b1"] and cursor == "9000"


def test_fetch_new_other_errors_are_raised(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    fake.history_pages = httpx.Response(
        403, json={"error": {"code": 403, "errors": [{"reason": "dailyLimitExceeded"}]}}
    )
    with pytest.raises(g.MailboxError) as err:
        mailbox.fetch_new("1")
    assert err.value.kind == "quota"


def test_reads_retry_transient_errors(fake: FakeGmail) -> None:
    calls: list[int] = []
    original = fake.handler

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/profile") and len(calls) < 2:
            calls.append(1)
            return httpx.Response(503, json={"error": {"code": 503, "message": "unavailable"}})
        return original(request)

    slept: list[float] = []
    box = g.GmailMailbox(
        ME,
        client_id="c",
        client_secret="s",
        refresh_token="r",
        transport=httpx.MockTransport(flaky),
        sleep=slept.append,
    )
    assert box.profile()["emailAddress"] == ME
    assert slept == [1.0, 2.0]


def test_mark_read_removes_the_unread_label(fake: FakeGmail, mailbox: g.GmailMailbox) -> None:
    mailbox.mark_read("r1")
    modify = next(r for r in fake.requests if r.url.path.endswith("/messages/r1/modify"))
    assert modify.method == "POST" and json.loads(modify.content) == {"removeLabelIds": ["UNREAD"]}


# ---------------------------------------------------------------------------
# Opening the mailbox
# ---------------------------------------------------------------------------


def test_connect_needs_the_oauth_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from nument_engine import settings as settings_module

    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    settings_module.get_settings.cache_clear()
    with pytest.raises(g.MailboxError) as err:
        g.connect(ME)
    assert err.value.kind == "auth" and "GMAIL_CLIENT_ID" in str(err.value)


def test_connect_without_a_vault_token(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from nument_engine import settings as settings_module

    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    settings_module.get_settings.cache_clear()
    assert g.refresh_token_for(ME) is None  # the test database has no Vault
    with pytest.raises(g.MailboxError) as err:
        g.connect(ME)
    assert err.value.kind == "auth" and "Vault" in str(err.value)


def test_connect_with_a_token(monkeypatch: pytest.MonkeyPatch, fake: FakeGmail) -> None:
    from nument_engine import settings as settings_module

    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    settings_module.get_settings.cache_clear()
    seen: list[str] = []

    def fake_vault(address: str) -> str:
        seen.append(address)
        return "1//from-vault"

    monkeypatch.setattr(g, "refresh_token_for", fake_vault)
    with g.connect("Hello.Nument@Gmail.com", transport=httpx.MockTransport(fake.handler)) as box:
        assert box.address == ME and box.access_token() == "ya29.t1"
    assert seen == ["Hello.Nument@Gmail.com"]
    form = parse_qs(next(r for r in fake.requests if r.url.host == "oauth2.googleapis.com").content.decode())
    assert form["refresh_token"] == ["1//from-vault"] and form["client_secret"] == ["client-secret"]


def test_vault_lookup_uses_the_secret_name(db_conn: Any) -> None:
    db_conn.execute("create schema vault")
    db_conn.execute("create table vault.decrypted_secrets (name text, decrypted_secret text)")
    db_conn.execute(
        "insert into vault.decrypted_secrets values (%s, '1//abc'), ('gmail_refresh_token:other@x.com', 'no')",
        [g.VAULT_PREFIX + ME],
    )
    assert g.refresh_token_for("Hello.Nument@gmail.com ", conn=db_conn) == "1//abc"
    assert g.refresh_token_for("nobody@gmail.com", conn=db_conn) is None
