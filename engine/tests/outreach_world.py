"""A small email-autopilot world for the reply-side tests (inbox, replies, bookings, briefs, proposals).

One startup lead in `firms-us` with a verified founder email, an open thread and the four sequence steps: day 0
sent, days 3 and 7 queued, day 12 waiting for review. Every world gets its own domain and ids, so tests that
share the session database never see each other's rows. All people and companies are fictional.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from nument_engine.outreach.gmail import FakeMailbox, Incoming
from nument_engine.pipeline.runs import Options, RunContext

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e5b"
MAILBOX = "hello.nument@gmail.com"
SEGMENT = "firms-us"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@contextmanager
def connect(dsn: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def rc_for(dry_run: bool = False, limit: int | None = None) -> RunContext:
    return RunContext(
        run_id=str(uuid.uuid4()),
        kind="outreach",
        opts=Options(limit=limit, dry_run=dry_run),
        started_at=datetime.now(UTC),
    )


@dataclass
class World:
    dsn: str
    tag: str
    business_id: str
    lead_id: str
    contact_id: str
    thread_id: str
    domain: str
    email: str
    gmail_thread_id: str
    mailbox: str = MAILBOX  # each world reads its own mailbox, so Gmail cursors never collide between tests
    steps: dict[int, str] = field(default_factory=dict)  # step -> message id
    rfc: dict[int, str] = field(default_factory=dict)  # step -> RFC Message-ID

    def one(self, query: str, params: list[Any] | None = None) -> dict[str, Any]:
        with connect(self.dsn) as conn:
            row = conn.execute(query, params or []).fetchone()
        assert row is not None, query
        return row

    def all(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        with connect(self.dsn) as conn:
            return conn.execute(query, params or []).fetchall()

    def run_sql(self, query: str, params: list[Any] | None = None) -> None:
        with connect(self.dsn) as conn:
            conn.execute(query, params or [])

    def thread(self) -> dict[str, Any]:
        return self.one("select * from public.email_threads where id = %s", [self.thread_id])

    def lead(self) -> dict[str, Any]:
        return self.one("select * from public.leads where id = %s", [self.lead_id])

    def contact(self) -> dict[str, Any]:
        return self.one("select * from public.contacts where id = %s", [self.contact_id])

    def statuses(self) -> dict[int, str]:
        rows = self.all(
            "select step, status from public.email_messages where thread_id = %s and step is not null",
            [self.thread_id],
        )
        return {r["step"]: r["status"] for r in rows}

    def incoming(self) -> list[dict[str, Any]]:
        return self.all(
            "select * from public.email_messages where thread_id = %s and direction = 'in' order by created_at",
            [self.thread_id],
        )

    def replies(self) -> list[dict[str, Any]]:
        return self.all(
            "select * from public.email_messages where thread_id = %s and direction = 'out' and step is null "
            "order by created_at",
            [self.thread_id],
        )

    def activities(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is None:
            return self.all("select * from public.activities where lead_id = %s order by at, id", [self.lead_id])
        return self.all(
            "select * from public.activities where lead_id = %s and type = %s order by at, id", [self.lead_id, kind]
        )

    def box(self) -> FakeMailbox:
        """An empty fake mailbox at this world's address."""
        return FakeMailbox(self.mailbox)

    def reply(
        self,
        body: str,
        *,
        n: int = 1,
        subject: str | None = None,
        sender: str | None = None,
        name: str | None = "Maya Chen",
        gmail_thread: str | None = "same",
        in_reply_to: str | None = "step0",
        at: datetime | None = None,
        **over: Any,
    ) -> Incoming:
        """An incoming reply to day 0 (by default threaded the way Gmail delivers it)."""
        return Incoming(
            gmail_message_id=f"in-{self.tag}-{n}",
            gmail_thread_id=self.gmail_thread_id if gmail_thread == "same" else (gmail_thread or f"other-{self.tag}"),
            rfc_message_id=f"<in-{self.tag}-{n}@mail.brightcart.example>",
            in_reply_to=self.rfc[0] if in_reply_to == "step0" else in_reply_to,
            from_email=sender or self.email,
            from_name=name,
            subject=subject if subject is not None else "Re: your seed round",
            body_text=body,
            received_at=at or datetime.now(UTC) - timedelta(minutes=5),
            **over,
        )


CREATED: list[tuple[str, str, str]] = []  # (dsn, lead id, business id) of every world, for cleanup


def cleanup() -> None:
    """Delete every world this process made, so tests elsewhere that count rows see none of ours."""
    while CREATED:
        dsn, _lead, business_id = CREATED.pop()
        with connect(dsn) as conn:
            conn.execute("delete from public.leads where business_id = %s", [business_id])
            conn.execute("delete from public.businesses where id = %s", [business_id])


def ensure_segment(conn: psycopg.Connection[dict[str, Any]]) -> None:
    conn.execute(
        "insert into public.segments (id, domain, country, display_name, enabled) "
        "values (%s, 'firms', 'us', 'Startups, US', true) on conflict (id) do nothing",
        [SEGMENT],
    )


def make_world(
    dsn: str,
    *,
    stage: str = "contacted",
    country: str = "us",
    city: str | None = "New York",
    company: str = "Brightcart",
    founder: str | None = "Maya Chen",
    step0_sent_days_ago: float = 1.0,
) -> World:
    tag = uuid.uuid4().hex[:10]
    domain = f"brightcart-{tag}.example"
    email = f"maya@{domain}"
    now = datetime.now(UTC)
    with connect(dsn) as conn:
        ensure_segment(conn)
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, website, web_domain, country, city, status) "
            "values (%s, %s, %s, %s, %s, %s, %s, 'qualified') returning id::text as id",
            [SEGMENT, company, f"{company.lower()} {tag}", f"https://{domain}", domain, country, city],
        ).fetchone()
        assert biz is not None
        score = conn.execute(
            "insert into public.scores (business_id, version, fit, total, grade, pitch_mode) "
            "values (%s, 's3.0', 3, 81, 'A', 'stated_need') returning id",
            [biz["id"]],
        ).fetchone()
        assert score is not None
        lead = conn.execute(
            "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, channel, message, "
            "email_subject, message_check_score) values (%s, %s, %s, 'A', 'stated_need', 'email', %s, %s, 9) "
            "returning id::text as id",
            [biz["id"], SEGMENT, score["id"], "Hi Maya, congrats on the pre-seed.", "your seed round"],
        ).fetchone()
        assert lead is not None
        if stage != "new":
            conn.execute("update public.leads set stage = %s where id = %s", [stage, lead["id"]])
        contact = conn.execute(
            "insert into public.contacts (business_id, name, role, email, source, source_url, is_decision_maker, "
            "verified, line, email_status, email_origin) values (%s, %s, 'Founder', %s, 'website', %s, true, true, "
            "'owner', 'verified', 'published') returning id::text as id",
            [biz["id"], founder, email, f"https://{domain}/about"],
        ).fetchone()
        assert contact is not None
        gmail_thread_id = f"gt-{tag}"
        thread = conn.execute(
            "insert into public.email_threads (lead_id, contact_id, to_email, to_domain, status, mode, "
            "gmail_thread_id) values (%s, %s, %s, %s, 'open', 'review', %s) returning id::text as id",
            [lead["id"], contact["id"], email, domain, gmail_thread_id],
        ).fetchone()
        assert thread is not None
        world = World(dsn, tag, biz["id"], lead["id"], contact["id"], thread["id"], domain, email, gmail_thread_id)
        world.mailbox = f"hello-{tag}@nument.example"
        CREATED.append((dsn, lead["id"], biz["id"]))
        sent_at = now - timedelta(days=step0_sent_days_ago)
        plan: list[tuple[int, str, datetime | None, str | None]] = [
            (0, "sent", None, "your seed round"),
            (3, "queued", sent_at + timedelta(days=3), None),
            (7, "queued", sent_at + timedelta(days=7), None),
            (12, "review", sent_at + timedelta(days=12), None),
        ]
        bodies = {
            0: "Hi Maya,\n\nCongrats on the pre-seed. Want me to send a 1-page plan for Brightcart?\n\nTeam Nument",
            3: "Hi Maya, here's the 1-page plan for Brightcart: {plan_link}\n\nTeam Nument",
            7: "Hi Maya, here's something similar we built: {case_study}\n\nTeam Nument",
            12: "Hi Maya, should I close this out, or is later better?\n\nTeam Nument",
        }
        for step, status, scheduled, subject in plan:
            rfc = f"<s{step}-{tag}@nument.in>" if status == "sent" else None
            row = conn.execute(
                "insert into public.email_messages (thread_id, direction, step, subject, body, status, scheduled_for, "
                "sent_at, rfc_message_id, gmail_message_id) values (%s, 'out', %s, %s, %s, %s, %s, %s, %s, %s) "
                "returning id::text as id",
                [
                    thread["id"],
                    step,
                    subject,
                    bodies[step],
                    status,
                    scheduled,
                    sent_at if status == "sent" else None,
                    rfc,
                    f"out-{tag}-{step}" if status == "sent" else None,
                ],
            ).fetchone()
            assert row is not None
            world.steps[step] = row["id"]
            if rfc:
                world.rfc[step] = rfc
    return world


def add_offer(
    world: World, offer_key: str = "nocode_to_app", why_now: str = "Raised a pre-seed, app is on Bubble"
) -> None:
    world.run_sql(
        "insert into public.lead_offers (lead_id, rank, offer_key, why_now, cited_ids) values (%s, 1, %s, %s, %s) "
        "on conflict (lead_id, rank) do nothing",
        [world.lead_id, offer_key, why_now, ["S1"]],
    )


def add_plan_page(world: World, token: str | None = None) -> str:
    token = token or uuid.uuid4().hex + "abcdef"
    world.run_sql(
        "insert into public.plan_pages (token, lead_id, content) values (%s, %s, %s)",
        [token, world.lead_id, Jsonb({"headline": "Brightcart app rebuild in 5 weeks"})],
    )
    return token
