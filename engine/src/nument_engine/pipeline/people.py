"""Who runs the business: the founder or owner of an A or B lead, through Google Search (plan 5.11.4, 13 Nov 2026).

A message that opens with "Hi Maya," gets more replies than "Hi,", and in the email-first countries (US, UK,
Australia, Canada, Singapore) a named person matters even more. Research reads the business's own pages; many
small companies never name their founder there. One grounded search per lead asks who runs it, and code keeps
the answer only when:

- a sentence the search results back contains the name (`reviews.supported_line`, the same rule as reviews);
- the role is one of a person in charge (`verify.DM_ROLE`: founder, owner, director, CEO, principal, partner);
- the line names this business (a distinctive word of its name).

The person is stored as a name-only contact (`source = 'other'`, the backing sentence as its quote, verified by
the search). Never a phone or an email: those come only from the business's own pages. LinkedIn and X stay
snippet-only. Each business is looked up once (`extra.dm_lookup_at`).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final

from .. import db
from ..logging import get_logger
from ..segments import country_name
from . import ai, score
from .reviews import supported_line
from .runs import RunContext
from .verify import DM_ROLE, distinctive_words

log = get_logger()

TASK: Final = "find_decision_maker"
SETTING: Final = "dm_lookup.per_day"
DEFAULT_PER_DAY: Final = 40

CANDIDATES_SQL: Final = """
select b.id::text as id, b.name, b.city, b.website, b.segment_id
  from public.leads l
  join public.businesses b on b.id = l.business_id
 where l.stage = 'new'
   and l.grade in ('A', 'B')
   and b.segment_id = any(%(segments)s)
   and not b.extra ? 'dm_lookup_at'
   and not exists (select 1 from public.contacts c where c.business_id = b.id and c.is_decision_maker
                   and c.name is not null and not c.do_not_contact)
 order by l.grade, l.created_at desc
 limit %(limit)s
"""


def names_business(line: str, business_name: str) -> bool:
    """Does the answer line name this business (a distinctive word of its name)?"""
    words = [w for w in distinctive_words(business_name) if len(w) >= 3] or business_name.lower().split()
    low = line.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low) for w in words)


def accepted(output: Any, grounding: dict[str, Any] | None, business_name: str) -> dict[str, str] | None:
    """{name, role, quote, url} when the search backs a person in charge of this business, else None."""
    name = str(getattr(output, "name", None) or "").strip()
    role = str(getattr(output, "role", None) or "").strip()
    line = str(getattr(output, "line", None) or "").strip()
    if not name or name.lower() in ("unknown", "none", "null") or len(name.split()) < 2:
        return None  # a full name only: "Maya" alone could be anyone
    if not role or not DM_ROLE.search(role):
        return None
    if not line or not names_business(line, business_name) or name.lower() not in line.lower():
        return None
    backed = supported_line(f"{name}, {role}", grounding) or supported_line(line, grounding)
    if backed is None or name.split()[-1].lower() not in backed[0].lower():
        return None
    return {"name": name[:120], "role": role[:80], "quote": backed[0], "url": backed[1] or ""}


def run(rc: RunContext, router: Any = None) -> dict[str, Any]:
    """`nlead people`: the founder or owner of new A and B leads that have no named decision maker."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = score.enabled_segments(rc)
    per_day = db.get_setting(SETTING, DEFAULT_PER_DAY)
    limit = int(per_day) if isinstance(per_day, int | float) else DEFAULT_PER_DAY
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "limit": limit})
    stats["candidates"] = len(rows)
    if rc.opts.dry_run or not rows:
        rc.stats["people"] = dict(stats)
        return dict(stats)
    router = router or ai.router_for(rc)
    run_result = getattr(router, "run_result", None) if router is not None else None
    if run_result is None:
        stats["skipped_no_router"] = len(rows)
        rc.stats["people"] = dict(stats)
        return dict(stats)
    budget = getattr(router, "budget", None)
    spent = 0.0
    for b in rows:
        quota = budget.grounding_quota_left() if budget is not None and hasattr(budget, "grounding_quota_left") else 1
        if quota is not None and quota <= 0:
            stats["stopped_quota"] += 1
            break
        if rc.time_left() <= 0:
            stats["stopped_time"] += 1
            break
        seg = segments[b["segment_id"]]
        try:
            res = run_result(
                TASK,
                {"name": b["name"], "city": b.get("city") or "", "country": country_name(seg.country),
                 "website": b.get("website") or ""},
            )  # fmt: skip
        except Exception as exc:  # typed router errors: stop on budget, skip one stubborn business
            name = type(exc).__name__
            stats[f"error.{name}"] += 1
            if name in ("BudgetExceeded", "BudgetStop"):
                break
            continue
        spent += float(getattr(res, "inr", 0) or 0)
        stats["looked_up"] += 1
        person = accepted(res.output, res.grounding, str(b["name"]))
        with db.tx("engine", {"run_id": rc.run_id, "stage": "people"}) as conn:
            if person:
                conn.execute(
                    "insert into public.contacts (business_id, name, role, source, source_url, quote, "
                    "is_decision_maker, verified, verified_at) "
                    "values (%s, %s, %s, 'other', %s, %s, true, true, now())",
                    [b["id"], person["name"], person["role"], person["url"] or None, person["quote"]],
                )
                stats["found"] += 1
            else:
                stats["not_found"] += 1
            conn.execute(
                "update public.businesses set extra = extra || jsonb_build_object('dm_lookup_at', %s::text) "
                "where id = %s",
                [now.isoformat(), b["id"]],
            )
    result: dict[str, Any] = {**stats, "inr": round(spent, 2)}
    rc.stats["people"] = result
    log.info("people.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
