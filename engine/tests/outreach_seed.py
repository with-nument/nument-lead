"""Seed data for the sending tests (lane E5a): a mailbox, leads with a founder contact, threads with the four
sequence steps. Rows are committed (the engine code uses its own pooled connections) and removed again by the
`outreach_world` fixture, which also restores every `outreach.*` setting."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from nument_engine.outreach.gmail import FakeMailbox, Outgoing, Sent
from nument_engine.pipeline.runs import Options, RunContext

ME = "hello.nument@gmail.com"
SEGMENT = "clinics-in"  # a seeded segment; the business's own country is what the gates read
POSTAL = "Nument, 12 Example Road, Pune 411001, India"
# Tuesday 17 Nov 2026, 15:00 UTC: 10:00 in New York and Toronto, 15:00 in London, 20:30 in India.
T0 = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
SUBJECT = "Quick question about {name}"
DAY0 = "Hi Maya,\n\nSaw {name} launch on Hacker News last week. Who is building the product right now?"
DAY3 = "Hi Maya, I sketched a plan for {name}: {plan_link}"
DAY7 = "Hi Maya, here is a similar build we did: {case_study}"
DAY12 = "Hi Maya, I will stop here. Happy to help whenever the time is right."


@contextmanager
def connect(dsn: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True) as conn:
        yield conn


class FakeClock:
    """The send loop's clock: sleeping moves time forward instantly."""

    def __init__(self, start: datetime = T0) -> None:
        self.at = start
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.at += timedelta(seconds=seconds)

    def advance(self, **kw: float) -> None:
        self.at += timedelta(**kw)


class ClockedMailbox(FakeMailbox):
    """FakeMailbox whose send times follow the test clock, and that can report another Message-ID."""

    def __init__(self, clock: FakeClock, address: str = ME) -> None:
        super().__init__(address)
        self.clock = clock
        self.replace_id: str | None = None
        self.lookups: list[tuple[str, str | None]] = []

    def send(self, message: Outgoing) -> Sent:
        sent = super().send(message)
        return Sent(
            sent.gmail_message_id, sent.gmail_thread_id, self.replace_id or sent.rfc_message_id, self.clock.now()
        )

    def find_sent(self, rfc_message_id: str, *, to: str | None = None) -> Sent | None:
        self.lookups.append((rfc_message_id, to))
        found = super().find_sent(rfc_message_id, to=to)
        return Sent(found.gmail_message_id, found.gmail_thread_id, rfc_message_id, self.clock.now()) if found else None


@dataclass
class World:
    dsn: str
    businesses: list[str] = field(default_factory=list)
    mailboxes: list[str] = field(default_factory=list)
    suppression: list[str] = field(default_factory=list)

    def conn(self) -> Any:
        return connect(self.dsn)

    # -- settings ---------------------------------------------------------------

    def setting(self, key: str, value: Any) -> None:
        with self.conn() as c:
            c.execute(
                "insert into public.settings (key, value) values (%s, %s::jsonb) "
                "on conflict (key) do update set value = excluded.value",
                [key, json.dumps(value)],
            )

    def outreach_on(self, mode: str = "manual", **extra: Any) -> None:
        self.setting("outreach.mode", mode)
        self.setting("outreach.paused", False)
        self.setting("outreach.postal_address", POSTAL)
        for key, value in extra.items():
            self.setting(f"outreach.{key}", value)

    # -- rows ---------------------------------------------------------------------

    def mailbox(self, *, status: str = "warming", started: date | None = None, email: str = ME) -> str:
        with self.conn() as c:
            row = c.execute(
                "insert into public.mailboxes (email, status, warmup_started_on, connected_at) "
                "values (%s, %s, %s, now()) returning id::text as id",
                [email, status, started],
            ).fetchone()
        assert row is not None
        self.mailboxes.append(row["id"])
        return str(row["id"])

    def lead(
        self,
        *,
        country: str = "us",
        city: str | None = "New York",
        address: str | None = None,
        stage: str = "new",
        score: float = 82,
        critic: float | None = 9.5,
        email_status: str = "verified",
        origin: str | None = "published",
        domain: str | None = None,
        do_not_contact: bool = False,
    ) -> dict[str, str]:
        tag = uuid.uuid4().hex[:8]
        domain = domain or f"acme-{tag}.example.com"
        email = f"maya@{domain}"
        with self.conn() as c:
            biz = c.execute(
                "insert into public.businesses (segment_id, name, norm_name, country, city, address) "
                "values (%s, %s, %s, %s, %s, %s) returning id::text as id",
                [SEGMENT, f"Acme {tag}", f"acme {tag}", country, city, address],
            ).fetchone()
            assert biz is not None
            self.businesses.append(biz["id"])
            score_row = c.execute(
                "insert into public.scores (business_id, version, fit, total, grade, pitch_mode) "
                "values (%s, 's3.0', 3, %s, 'A', 'stated_need') returning id",
                [biz["id"], score],
            ).fetchone()
            assert score_row is not None
            contact = c.execute(
                "insert into public.contacts (business_id, name, role, email, source, is_decision_maker, "
                "email_status, email_origin, do_not_contact) values (%s, 'Maya Rao', 'Founder', %s, 'website', true, "
                "%s, %s, %s) returning id::text as id",
                [biz["id"], email, email_status, origin, do_not_contact],
            ).fetchone()
            assert contact is not None
            lead = c.execute(
                "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, channel, "
                "message_check_score, stage) values (%s, %s, %s, 'A', 'stated_need', 'email', %s, %s) "
                "returning id::text as id",
                [biz["id"], SEGMENT, score_row["id"], critic, stage],
            ).fetchone()
            assert lead is not None
        return {"lead": lead["id"], "business": biz["id"], "contact": contact["id"], "email": email, "domain": domain}

    def thread(
        self,
        lead: dict[str, str],
        *,
        day0: str = "approved",
        followups: str = "draft",
        status: str = "open",
        mode: str = "review",
        name: str = "Acme",
        steps: tuple[int, ...] = (0, 3, 7, 12),
        day0_body: str | None = None,
        day0_subject: str | None = None,
        paused_until: datetime | None = None,
        created: datetime | None = None,
    ) -> dict[str, Any]:
        bodies = {
            0: day0_body or DAY0.format(name=name),
            3: DAY3.format(name=name, plan_link="{plan_link}"),
            7: DAY7.format(case_study="{case_study}"),
            12: DAY12,
        }
        with self.conn() as c:
            thread = c.execute(
                "insert into public.email_threads (lead_id, contact_id, to_email, to_domain, mode, status, "
                "paused_until, created_at) values (%s, %s, %s, %s, %s, %s, %s, coalesce(%s, now())) "
                "returning id::text as id",
                [lead["lead"], lead["contact"], lead["email"], lead["domain"], mode, status, paused_until, created],
            ).fetchone()
            assert thread is not None
            ids: dict[int, str] = {}
            for step in steps:
                subject = (day0_subject or SUBJECT.format(name=name)) if step == 0 else None
                row = c.execute(
                    "insert into public.email_messages (thread_id, direction, step, subject, body, status, created_at) "
                    "values (%s, 'out', %s, %s, %s, %s, coalesce(%s, now())) returning id::text as id",
                    [thread["id"], step, subject, bodies[step], day0 if step == 0 else followups, created],
                ).fetchone()
                assert row is not None
                ids[step] = row["id"]
        return {"id": thread["id"], "steps": ids, **lead}

    def message(self, thread_id: str, **cols: Any) -> str:
        values = {"thread_id": thread_id, "direction": "out", **cols}
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        with self.conn() as c:
            row = c.execute(
                f"insert into public.email_messages ({names}) values ({marks}) returning id::text as id",
                list(values.values()),
            ).fetchone()
        assert row is not None
        return str(row["id"])

    def suppress(self, *, email: str | None = None, domain: str | None = None) -> None:
        with self.conn() as c:
            row = c.execute(
                "insert into public.suppression (email, web_domain, reason) values (%s, %s, 'opt_out') "
                "returning id::text as id",
                [email, domain],
            ).fetchone()
        assert row is not None
        self.suppression.append(row["id"])

    def update(self, sql: str, params: list[Any] | dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(sql, params)

    def one(self, sql: str, params: list[Any] | dict[str, Any] | None = None) -> dict[str, Any]:
        with self.conn() as c:
            row = c.execute(sql, params).fetchone()
        assert row is not None, sql
        return dict(row)

    def all(self, sql: str, params: list[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def msg(self, message_id: str) -> dict[str, Any]:
        return self.one("select * from public.email_messages where id = %s", [message_id])

    def thread_row(self, thread_id: str) -> dict[str, Any]:
        return self.one("select * from public.email_threads where id = %s", [thread_id])

    # -- cleanup --------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        return self.all("select key, value from public.settings where key like 'outreach.%'")

    def restore(self, snapshot: list[dict[str, Any]]) -> None:
        with self.conn() as c:
            if self.businesses:
                c.execute(
                    "delete from public.leads where business_id = any(%s::uuid[])", [self.businesses]
                )  # cascades threads, messages, activities
                c.execute("delete from public.businesses where id = any(%s::uuid[])", [self.businesses])
            if self.mailboxes:
                c.execute("delete from public.mailboxes where id = any(%s::uuid[])", [self.mailboxes])
            if self.suppression:
                c.execute("delete from public.suppression where id = any(%s::uuid[])", [self.suppression])
            c.execute("delete from public.settings where key like 'outreach.%'")
            for row in snapshot:
                c.execute("insert into public.settings (key, value) values (%s, %s)", [row["key"], Jsonb(row["value"])])


def rc(*, env: str = "prod", dry_run: bool = False, limit: int | None = None) -> RunContext:
    return RunContext(
        run_id=str(uuid.uuid4()),
        kind="outreach",
        opts=Options(env=env, dry_run=dry_run, limit=limit),
        started_at=datetime.now(UTC),
    )
