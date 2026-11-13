"""Careers and locations page watcher: hiring and new-branch signals from businesses we already know (Step 5.9).

Research (Step 9) records each business's careers and locations page as a code fact and stores the page text with
its hash. Every night this watcher re-fetches those pages (robots.txt obeyed, one page per host a night, oldest
first, at most `careers_watch.pages_per_day`). When the text changed, only the added lines go to
`classify_page_change`; navigation and footer lines shared with the business's other pages are ignored first, so
a new menu item does not cost an AI call.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import db
from ..http import NeverFetch, SourceBlocked, host_of
from ..normalize import canonical_url
from ..research.text import page_text
from . import health
from .base import QUOTE_MAX, Signal, SourceAdapter, field_of
from .jobs import quote_in

DEFAULT_PAGES_PER_DAY = 500
MIN_ADDED_CHARS = 20  # less new text than this is cosmetic
ADDED_TEXT_CHARS = 2000  # Step 7.5.2: diff only, at most 2,000 characters

WATCH_SQL = """
select p.id as page_id, p.url, p.text, p.text_hash, p.fetched_at, f.field, b.id as business_id, b.name,
       b.segment_id
from public.facts f
join public.businesses b on b.id = f.business_id
join public.pages p on p.business_id = b.id
 and (p.id = f.page_id or (f.page_id is null and p.url = f.value->>'url'))
where f.field in ('careers_url', 'locations_url')
  and f.model in ('rule', 'code')
  and (b.status in ('researched', 'qualified')
       or exists (select 1 from public.leads l where l.business_id = b.id
                  and l.stage not in ('won','retainer','lost','not_now','not_a_fit','wrong_contact')))
  and p.text is not null
  and p.fetched_at < now() - interval '20 hours'
  and b.segment_id = any(%(segments)s)
order by p.fetched_at asc
limit %(limit)s
"""


@dataclass
class WatchTarget:
    page_id: str
    url: str
    text: str
    text_hash: str | None
    fetched_at: datetime
    field: str
    business_id: str
    name: str
    segment_id: str


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def added_lines(old: str, new: str, chrome: set[str] | None = None) -> list[str]:
    """Lines that are in the new text and not in the old one, minus site-wide navigation and footer lines."""
    chrome = chrome or set()
    out = []
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("+ "):
            text = line[2:].strip()
            if len(text) >= 3 and text not in chrome:
                out.append(text)
    return out


def chrome_lines(business_id: str, exclude_url: str) -> set[str]:
    """Lines that appear on the business's other pages (navigation, footer, address blocks)."""
    rows = db.fetch_all(
        "select text from public.pages where business_id = %s and url <> %s and text is not null",
        [business_id, exclude_url],
    )
    lines: set[str] = set()
    for row in rows:
        lines.update(line.strip() for line in (row["text"] or "").splitlines() if line.strip())
    return lines


class CareersWatchAdapter(SourceAdapter):
    name = "careers_watch"
    policy = "public"
    min_gap_s = 2.0  # business websites (Step 18.1.3)

    @staticmethod
    def targets(segment_ids: list[str], limit: int) -> list[WatchTarget]:
        rows = db.fetch_all(WATCH_SQL, {"segments": segment_ids, "limit": limit * 3})
        seen_hosts: set[str] = set()
        out: list[WatchTarget] = []
        for row in rows:  # one page per host per night
            host = host_of(row["url"])
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            out.append(
                WatchTarget(
                    page_id=str(row["page_id"]),
                    url=row["url"],
                    text=row["text"],
                    text_hash=row["text_hash"],
                    fetched_at=row["fetched_at"],
                    field=row["field"],
                    business_id=str(row["business_id"]),
                    name=row["name"],
                    segment_id=row["segment_id"],
                )
            )
            if len(out) >= limit:
                break
        return out

    def classify(self, target: WatchTarget, new_text: str, added: list[str]) -> Signal | None:
        added_text = "\n".join(added)[:ADDED_TEXT_CHARS]
        result = self.ctx.ai(
            "classify_page_change",
            {
                "business_name": target.name,
                "url": target.url,
                "page_kind": "careers" if target.field == "careers_url" else "locations",
                "old_date": target.fetched_at.date().isoformat(),
                "old_text": target.text[:ADDED_TEXT_CHARS],
                "new_date": datetime.now(UTC).date().isoformat(),
                "new_text": added_text,
                "added_text": added_text,
            },
        )
        if result is None:
            return None
        sig_type = field_of(result, "signal_type")
        quote = (field_of(result, "quote") or "").strip()
        if sig_type not in ("hiring_frontdesk", "hiring_builder", "new_branch"):
            self.ctx.add("careers_watch.no_signal")
            return None
        if not quote_in(quote, new_text):
            self.ctx.add("careers_watch.quote_not_found")
            return None
        quote = quote[:QUOTE_MAX]
        return Signal(
            type=str(sig_type),
            source=self.name,
            observed_at=datetime.now(UTC),
            url=target.url,
            quote=quote,
            evidence_key=f"{canonical_url(target.url)}|{hashlib.sha1(quote.encode()).hexdigest()[:12]}",
            business_id=target.business_id,
            details={
                "date_estimated": True,  # we saw the change now; the page has no date
                "change_type": field_of(result, "change_type"),
                "roles": list(field_of(result, "roles") or [])[:5],
                **({"event_key": f"growth:{datetime.now(UTC):%Y-%m}"} if sig_type == "new_branch" else {}),
            },
        )

    async def check(self, target: WatchTarget) -> Signal | None:
        """Re-fetch one page; when it changed, classify the added text and store the new version."""
        try:
            res = await self.http.get(target.url, retries=1)
        except SourceBlocked:
            self.ctx.add("careers_watch.host_blocked")
            return None
        except NeverFetch:
            return None
        if not res.ok:
            self.ctx.add(f"careers_watch.{res.state}")
            return None
        text, title = page_text(res.text, res.final_url)
        new_hash = text_hash(text)
        sig = None
        if new_hash != target.text_hash:
            self.ctx.add("careers_watch.changed")
            added = added_lines(target.text, text, chrome_lines(target.business_id, target.url))
            if sum(len(a) for a in added) >= MIN_ADDED_CHARS:
                sig = self.classify(target, text, added)
            else:
                self.ctx.add("careers_watch.cosmetic")
        if not self.ctx.dry_run:
            db.execute(
                "update public.pages set text = %s, text_hash = %s, title = coalesce(%s, title), "
                "fetched_at = now(), http_status = %s where id = %s",
                [text, new_hash, title, res.status, target.page_id],
            )
        return sig

    async def watch(self, segment_ids: list[str], *, limit: int | None = None) -> list[Signal]:
        cap = health.setting_int("careers_watch.pages_per_day", DEFAULT_PAGES_PER_DAY)
        targets = self.targets(segment_ids, min(cap, limit or cap))
        self.ctx.add("careers_watch.targets", len(targets))
        out: list[Signal] = []
        for target in targets:
            sig = await self.check(target)
            if sig is not None:
                out.append(sig)
        return out
