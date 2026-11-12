"""`nlead health`: every service, source and quota in one look, plus retention pruning.

Checks (Steps 2.13, 4.5, 19 and 22): database reachable and its size (warning at 350 MB, A.13.5 rule 13;
"act now" at 400 MB of the 500 MB free tier), pending migrations, provider switches and keys, spend today
against the cap, free quotas, source health, AI circuit breakers, the last run of each kind and stuck AI
batches. Status per check: ok, info, warn, alert (tell the founder) or fail (unsafe to run the pipeline).

`check_all(fail_fast=True)` is the first phase of the night and morning runs: it stops the run only on
`fail`. `daily_summary()` is the morning job summary (19.8). `prune()` applies the retention rules
(18.2.2, with A.13.5 rule 13 winning where they differ). `notify()` emails new alerts once a day.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import psycopg

from .. import db
from ..learn import fmt
from ..learn.metrics import ist_day_start
from ..logging import get_logger
from ..pipeline.runs import RunContext
from ..settings import get_settings
from . import migrate, notify

log = get_logger()

Status = Literal["ok", "info", "warn", "alert", "fail"]
SEVERITY: Final[dict[str, int]] = {"ok": 0, "info": 1, "warn": 2, "alert": 3, "fail": 4}
DB_WARN_MB, DB_ALERT_MB, DB_LIMIT_MB = 350.0, 400.0, 500.0
STUCK_RUN_HOURS: Final[int] = 3
STUCK_BATCH_HOURS: Final[int] = 24
QUOTA_WARN: Final[float] = 0.9
GROUNDED_MONTHLY_FREE: Final[int] = 5000
PLACES_DETAILS_MONTHLY_FREE: Final[int] = 7000
RUN_MAX_AGE_HOURS: Final[dict[str, int]] = {
    "night": 26,
    "morning": 26,
    "sheet_sync": 6,
    "weekly": 8 * 24,
    "monthly": 32 * 24,
}

# Retention (Step 18.2.2; A.13.5 rule 13 wins: page text 30 days, 90 for leads, trimmed to 20,000 characters)
PLACES_DAYS: Final[int] = 30
TEXT_DAYS: Final[int] = 30
LEAD_TEXT_DAYS: Final[int] = 90
PAGE_ROW_DAYS: Final[int] = 90
OPS_DAYS: Final[int] = 365
PAGE_TEXT_MAX: Final[int] = 20_000
ALERTS_KEY: Final[str] = "health_alerts_sent"


class HealthCheckFailed(RuntimeError):
    """A check failed: running the pipeline now would be unsafe or pointless."""


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "data": self.data}


def worst(checks: Sequence[Check]) -> Status:
    return max((c.status for c in checks), key=SEVERITY.__getitem__, default="ok")


# ---------------------------------------------------------------------------
# Individual checks (each takes the connection and returns one or more Check)
# ---------------------------------------------------------------------------


def check_database(conn: Any) -> Check:
    size = float(db.scalar("select public.db_size_mb()", conn=conn) or 0)
    data = {"size_mb": size, "limit_mb": DB_LIMIT_MB}
    detail = f"reachable, {size:.1f} MB of {DB_LIMIT_MB:.0f} MB"
    if size >= DB_ALERT_MB:
        return Check("database", "alert", f"{detail}: act now (prune, shorter retention or Supabase Pro)", data)
    if size >= DB_WARN_MB:
        return Check("database", "warn", f"{detail}: decide on retention or an upgrade soon", data)
    return Check("database", "ok", detail, data)


def check_migrations(conn: Any) -> Check:
    rows = migrate.status(conn)
    pending = [m.filename for m, applied in rows if not applied]
    if pending:
        return Check("migrations", "fail", f"{len(pending)} pending: {', '.join(pending)}", {"pending": pending})
    return Check("migrations", "ok", f"{len(rows)} applied", {"applied": len(rows)})


AUTO_OPENAI_KEY = "providers_auto.openai"  # false = the founder decides by hand; default: switch by itself


def probe_openai(timeout_s: float = 20.0) -> bool | None:
    """True when OpenAI answers a model-list call (free), False when the key is refused, None when unsure."""
    import httpx

    s = get_settings()
    gateway = s.et_gateway_key.get_secret_value() if s.et_gateway_key is not None else ""
    direct = s.openai_api_key.get_secret_value() if s.openai_api_key is not None else ""
    key = gateway or direct
    if not key:
        return None
    base = f"{s.gateway_base_url.rstrip('/')}/openai/v1" if gateway else "https://api.openai.com/v1"
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=timeout_s)
    except httpx.HTTPError:
        return None
    if r.status_code == 200:
        return True
    return False if r.status_code in (401, 403) else None


def auto_switch_openai(conn: Any, probe: Any = None) -> Check | None:
    """Turn OpenAI on the day the gateway (or a direct key) lets it answer, and off again when it is refused.

    Runs with every health check (start of the night and morning runs), so no code or setting change is needed
    when OpenAI goes live. Sends one alert email on each switch. `providers_auto.openai = false` stops it.
    """
    if db.get_setting(AUTO_OPENAI_KEY, True, conn=conn) is False:
        return None
    works = (probe or probe_openai)()
    if works is None:
        return None
    enabled = dict(db.get_setting("providers_enabled", {}, conn=conn) or {})
    if bool(enabled.get("openai", False)) == works:
        return None
    enabled["openai"] = works
    db.set_setting("providers_enabled", enabled, conn=conn)
    detail = (
        "switched on by itself: OpenAI now answers, so it shares the work with Gemini"
        if works
        else "switched off by itself: OpenAI refused the key; Gemini runs every task"
    )
    log.warning("ai.openai_auto_switch", on=works)
    try:
        from . import emails

        if notify.email_configured():
            emails.send_alerts([emails.alert_item("ai.openai", "warn", detail)])
    except Exception as exc:  # the switch itself must never fail a run
        log.warning("ai.openai_switch_email_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    return Check("ai.openai.switch", "info", detail)


def check_providers(conn: Any) -> list[Check]:
    s = get_settings()
    enabled = db.get_setting("providers_enabled", {}, conn=conn) or {}
    out: list[Check] = []
    if not enabled.get("gemini", False):
        out.append(Check("ai.gemini", "fail", "providers_enabled.gemini is off: Gemini must run every task (A.2.4)"))
    elif not (s.gemini_api_key or s.et_gateway_key):
        out.append(Check("ai.gemini", "fail", "neither ET_GATEWAY_KEY nor GEMINI_API_KEY is set"))
    else:
        backup = "with a backup key" if s.gemini_api_key_backup else "no backup key"
        out.append(Check("ai.gemini", "ok", f"on, key set, {backup}"))
    if enabled.get("openai", False):
        has_key = bool(s.openai_api_key or s.et_gateway_key)
        status: Status = "ok" if has_key else "warn"
        out.append(Check("ai.openai", status, "on" + ("" if has_key else ", but no OpenAI or gateway key is set")))
    else:
        out.append(Check("ai.openai", "info", "off (providers_enabled.openai = false); Gemini runs every task"))
    breakers = db.fetch_all(
        "select source, blocked_until, last_error from public.source_health "
        "where starts_with(source, 'llm:') and blocked_until > now() order by source",
        conn=conn,
    )
    for b in breakers:
        provider = b["source"].split(":", 1)[1]
        level: Status = "alert" if provider == "gemini" else "warn"
        out.append(
            Check(
                f"ai.{provider}.breaker",
                level,
                f"circuit breaker open until {fmt.when(b['blocked_until'])}: {str(b['last_error'] or '')[:120]}",
            )
        )
    return out


def check_keys() -> list[Check]:
    s = get_settings()
    out = [
        Check(
            "google.maps_key",
            "ok" if s.google_maps_api_key else "warn",
            "set" if s.google_maps_api_key else "GOOGLE_MAPS_API_KEY not set: Places and PageSpeed are skipped",
        ),
    ]
    has_sa = bool(s.google_service_account_json or s.google_service_account_file)
    sheets = s.target_sheets()
    if not has_sa:
        out.append(
            Check("sheets", "alert" if s.app_env == "prod" else "info", "no Google service account: sheet sync is off")
        )
    elif not all(sheets.values()):
        out.append(Check("sheets", "info", "no staging sheet id: dev sheet sync is off"))
    else:
        out.append(Check("sheets", "ok", f"{len(sheets)} sheet(s): {', '.join(sheets)}"))
    return out


def check_spend(conn: Any) -> Check:
    spend = db.fetch_one("select inr::float as inr, usd::float as usd from public.v_spend_today", conn=conn) or {}
    cap = float(db.get_setting("daily_cap_inr", 750, conn=conn))
    alert_pct = float(db.get_setting("alert_pct", 80, conn=conn))
    inr = float(spend.get("inr") or 0.0)
    data = {"inr": inr, "cap_inr": cap, "alert_pct": alert_pct}
    detail = f"{fmt.inr(inr)} of {fmt.inr(cap)} today ({fmt.pct(inr / cap if cap else None)})"
    if cap and inr >= cap:
        return Check("spend", "alert", f"{detail}: cap reached, paid work has stopped for today", data)
    if cap and inr >= cap * alert_pct / 100:
        return Check("spend", "warn", f"{detail}: past the {alert_pct:.0f}% alert line", data)
    return Check("spend", "ok", detail, data)


def _setting_int(conn: Any, keys: Sequence[str], default: int) -> int:
    """The first of several settings keys that exists (later steps renamed a few caps, A.13.4)."""
    for key in keys:
        value = db.get_setting(key, None, conn=conn)
        if value is not None:
            return int(value)
    return default


QUOTA_SPECS: Final[tuple[tuple[str, str, str, tuple[str, ...], int, int], ...]] = (
    ("quota.grounded_search", "google_search", "", ("grounding_daily_cap", "grounded_search.per_day"), 160,
     GROUNDED_MONTHLY_FREE),
    ("quota.places_details", "google_places", "details", ("places_details_daily_cap", "places_details_cap_in"), 230,
     PLACES_DETAILS_MONTHLY_FREE),
)  # fmt: skip


def check_quotas(conn: Any) -> list[Check]:
    """Free allowances: calls today against the daily cap, and this month against the free monthly amount."""
    today = db.fetch_all("select provider, task, calls from public.v_quota_today", conn=conn)
    month = db.fetch_all("select provider, task, calls from public.v_quota_month", conn=conn)

    def used(rows: Sequence[Mapping[str, Any]], provider: str, needle: str) -> int:
        return sum(int(r["calls"]) for r in rows if r["provider"] == provider and needle in r["task"])

    out: list[Check] = []
    for name, provider, needle, keys, default_cap, monthly in QUOTA_SPECS:
        day_cap = _setting_int(conn, keys, default_cap)
        day, mon = used(today, provider, needle), used(month, provider, needle)
        level: Status = "warn" if day >= QUOTA_WARN * day_cap or mon >= QUOTA_WARN * monthly else "ok"
        detail = f"{day} of {day_cap} today, {mon} of {monthly} free this month"
        out.append(Check(name, level, detail, {"day": day, "day_cap": day_cap, "month": mon, "month_free": monthly}))
    return out


def check_sources(conn: Any, env: str) -> list[Check]:
    rows = db.fetch_all(
        "select source, enabled, health, blocked_until, last_ok_at, last_error, requests_today "
        "from public.v_source_health where not starts_with(source, 'llm:') order by source",
        conn=conn,
    )
    out: list[Check] = []
    for r in rows:
        name = f"source.{r['source']}"
        if r["health"] == "blocked":
            out.append(Check(name, "warn", f"blocked until {fmt.when(r['blocked_until'])}; never work around a block"))
        elif r["health"] == "error":
            out.append(Check(name, "warn", f"last call failed: {str(r['last_error'] or '')[:120]}"))
        elif r["health"] == "disabled":
            out.append(Check(name, "info", "switched off"))
        elif r["health"] == "stale":
            seen = fmt.when(r["last_ok_at"]) if r["last_ok_at"] else "never"
            out.append(Check(name, "warn" if env == "prod" else "info", f"no successful call in 3 days (last: {seen})"))
        else:
            out.append(Check(name, "ok", f"{r['requests_today']} requests today"))
    return out


def check_runs(conn: Any, env: str, now: datetime) -> list[Check]:
    latest = db.fetch_all(
        "select distinct on (kind) kind, status, started_at, finished_at, error from public.runs "
        "order by kind, started_at desc",
        conn=conn,
    )
    by_kind = {r["kind"]: r for r in latest}
    out: list[Check] = []
    for kind, max_age in RUN_MAX_AGE_HOURS.items():
        r = by_kind.get(kind)
        name = f"run.{kind}"
        if r is None:
            out.append(Check(name, "warn" if env == "prod" and kind in ("night", "morning") else "info", "never ran"))
            continue
        age = now - r["started_at"]
        detail = f"{r['status']}, started {fmt.when(r['started_at'])}"
        if r["status"] == "running" and age > timedelta(hours=STUCK_RUN_HOURS):
            out.append(Check(name, "warn", f"{detail}: still running after {STUCK_RUN_HOURS} hours (stuck?)"))
        elif r["status"] == "failed":
            last = [ln for ln in str(r["error"] or "").strip().splitlines() if ln.strip()]
            out.append(Check(name, "alert", f"{detail}: failed ({(last[-1] if last else 'no error text')[:120]})"))
        elif r["status"] == "partial":
            out.append(Check(name, "warn", f"{detail}: some stages were skipped or failed"))
        elif age > timedelta(hours=max_age):
            out.append(Check(name, "warn" if env == "prod" else "info", f"{detail}: older than {max_age} hours"))
        else:
            out.append(Check(name, "ok", detail))
    return out


def check_batches(conn: Any) -> Check:
    stuck = int(
        db.scalar(
            "select count(*) from public.llm_batches where status in ('submitted', 'running') "
            "and submitted_at < now() - make_interval(hours => %s)",
            [STUCK_BATCH_HOURS],
            conn=conn,
        )
        or 0
    )
    if stuck:
        return Check(
            "ai.batches",
            "warn",
            f"{stuck} batch(es) waiting over {STUCK_BATCH_HOURS} hours: "
            "nlead extract collect --force-sync re-runs them",
            {"stuck": stuck},
        )
    return Check("ai.batches", "ok", "no batch waiting over 24 hours", {"stuck": 0})


def collect(conn: Any = None, *, now: datetime | None = None) -> list[Check]:
    """Every check, in display order, on one connection."""
    if conn is None:
        with db.pool().connection() as pooled:
            return collect(pooled, now=now)
    now = now or datetime.now(UTC)
    env = get_settings().app_env
    checks = [check_database(conn), check_migrations(conn)]
    switched = auto_switch_openai(conn)
    if switched is not None:
        checks.append(switched)
    checks += check_providers(conn)
    checks += check_keys()
    checks.append(check_spend(conn))
    checks += check_quotas(conn)
    checks += check_sources(conn, env)
    checks += check_runs(conn, env, now)
    checks.append(check_batches(conn))
    return checks


def check_all(rc: RunContext | None = None, *, fail_fast: bool = False) -> dict[str, Any]:
    """Run every check. With fail_fast, raise HealthCheckFailed on any `fail` (first phase of night and morning)."""
    checks = collect()
    status = worst(checks)
    result = {"status": status, "checks": [c.as_dict() for c in checks]}
    if rc is not None:
        rc.stats["health"] = {"status": status, "problems": [c.name for c in checks if SEVERITY[c.status] >= 2]}
    if fail_fast and status == "fail":
        failed = "; ".join(f"{c.name}: {c.detail}" for c in checks if c.status == "fail")
        raise HealthCheckFailed(failed)
    return result


def run(rc: RunContext) -> dict[str, Any]:
    """The health phase of the night and morning runs: every check, stopping the run only on a failure."""
    return check_all(rc, fail_fast=True)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

ICONS: Final[dict[str, str]] = {"ok": "ok", "info": "info", "warn": "WARN", "alert": "ALERT", "fail": "FAIL"}


def render_text(checks: Sequence[Check]) -> str:
    """Plain columns for the terminal."""
    width = max((len(c.name) for c in checks), default=10) + 2
    lines = [f"{'check':<{width}}{'status':<8}detail"]
    lines += [f"{c.name:<{width}}{ICONS[c.status]:<8}{c.detail}" for c in checks]
    lines.append(f"\noverall: {ICONS[worst(checks)]}")
    return "\n".join(lines)


TODAY_SQL = """
select
  (select coalesce(sum(inr), 0)::float from public.costs where at >= %(day)s) as spend_today,
  (select coalesce(sum(inr), 0)::float from public.costs where at >= %(month)s) as spend_month,
  (select count(*)::int from public.businesses where researched_at >= %(day)s) as researched,
  (select count(*)::int from public.leads where created_at >= %(day)s) as leads,
  (select count(*)::int from public.leads where created_at >= %(day)s and grade = 'A') as grade_a,
  (select count(*)::int from public.leads where created_at >= %(day)s and grade = 'B') as grade_b
"""


def daily_summary(rc: RunContext | None = None, *, now: datetime | None = None) -> str:
    """Markdown for the GitHub job summary and the morning report (19.8): health plus today's numbers."""
    now = now or datetime.now(UTC)
    checks = collect(now=now)
    today = now.astimezone(fmt.IST).date()
    numbers = db.fetch_one(TODAY_SQL, {"day": ist_day_start(today), "month": ist_day_start(today.replace(day=1))}) or {}
    tasks = db.fetch_all(
        "select task, sum(inr)::float as inr from public.costs where at >= %s group by 1 order by 2 desc limit 5",
        [ist_day_start(today)],
    )
    leads, spend = int(numbers.get("leads") or 0), float(numbers.get("spend_today") or 0)
    researched = int(numbers.get("researched") or 0)
    lines = [
        f"### Nument Leads health, {fmt.when(now)}",
        "",
        f"**Today:** spend {fmt.inr(spend)} (this month {fmt.inr(numbers.get('spend_month'))}) · researched "
        f"{researched} · new leads {leads} (A {numbers.get('grade_a', 0)}, B {numbers.get('grade_b', 0)}) · per "
        f"researched business {fmt.inr(spend / researched if researched else None, 2)} · per new lead "
        f"{fmt.inr(spend / leads if leads else None, 2)}",
    ]
    if tasks:
        lines.append("**Spend by task:** " + ", ".join(f"{t['task']} {fmt.inr(t['inr'], 2)}" for t in tasks))
    lines += ["", fmt.table(["Check", "Status", "Detail"], [[c.name, ICONS[c.status], c.detail] for c in checks])]
    text = "\n".join(lines) + "\n"
    if rc is not None:
        rc.stats["summary"] = {"status": worst(checks), "spend_today_inr": spend, "leads": leads}
    return text


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

_NOT_A_LEAD = "not exists (select 1 from public.leads l where l.business_id = p.business_id)"
_A_LEAD = "exists (select 1 from public.leads l where l.business_id = p.business_id)"
_NOT_GOLDEN = "not exists (select 1 from public.golden_labels g where g.business_id = p.business_id)"
PRUNE_STEPS: Final[tuple[tuple[str, str], ...]] = (
    # Google Places content older than 30 days, unless refreshed (A.4.4, 18.5). place_id stays.
    ("places_content",
     "update public.businesses set rating = null, review_count = null "
     "where places_fetched_at < %(places)s and (rating is not null or review_count is not null)"),
    # Phones from a Google listing that were not re-verified within 30 days (10.3.4). Opt-outs stay.
    ("google_listing_contacts",
     "delete from public.contacts where source = 'google_listing' "
     "and coalesce(verified_at, created_at) < %(places)s and not do_not_contact"),
    ("page_text_trimmed",
     f"update public.pages set text = left(text, {PAGE_TEXT_MAX}) where length(text) > {PAGE_TEXT_MAX}"),
    # Page text: 30 days, or 90 for businesses that became leads. URL, hash and date stay. Golden pages stay.
    ("page_text_not_leads",
     f"update public.pages p set text = null where p.text is not null and p.fetched_at < %(text)s "
     f"and {_NOT_A_LEAD} and {_NOT_GOLDEN}"),
    ("page_text_leads",
     f"update public.pages p set text = null where p.text is not null and p.fetched_at < %(lead_text)s "
     f"and {_A_LEAD} and {_NOT_GOLDEN}"),
    # Page rows of businesses that never became leads, after 90 days (facts keep their quote and URL).
    ("page_rows_not_leads",
     f"delete from public.pages p where p.fetched_at < %(rows)s and {_NOT_A_LEAD} and {_NOT_GOLDEN}"),
    ("llm_cache_expired", "delete from public.llm_cache where expires_at < %(now)s"),
    ("costs_older_than_a_year", "delete from public.costs where at < %(ops)s"),
    ("runs_older_than_a_year", "delete from public.runs where started_at < %(ops)s and status <> 'running'"),
)  # fmt: skip


def prune(conn: Any = None, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
    """Apply the retention rules in one transaction and return rows affected per rule. A dry run counts the
    same rows and rolls back. Suppression, leads, activities, facts and signals are never touched."""
    if conn is None:
        with db.pool().connection() as pooled:
            return prune(pooled, now=now, dry_run=dry_run)
    now = now or datetime.now(UTC)
    params = {
        "now": now,
        "places": now - timedelta(days=PLACES_DAYS),
        "text": now - timedelta(days=TEXT_DAYS),
        "lead_text": now - timedelta(days=LEAD_TEXT_DAYS),
        "rows": now - timedelta(days=PAGE_ROW_DAYS),
        "ops": now - timedelta(days=OPS_DAYS),
    }
    counts: dict[str, int] = {}
    with conn.transaction():  # a savepoint when the caller already has a transaction open
        for name, query in PRUNE_STEPS:
            counts[name] = conn.execute(query, params).rowcount
        if dry_run:
            raise psycopg.Rollback()  # undo everything counted above; the exception stops here
    return counts


def prune_run(rc: RunContext) -> dict[str, int]:
    """The prune phase (morning and monthly runs, and `nlead health --prune`)."""
    counts = prune(dry_run=rc.opts.dry_run)
    rc.stats["prune"] = {"dry_run": rc.opts.dry_run, **counts}
    log.info("health.prune", dry_run=rc.opts.dry_run, **counts)
    return counts


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def alert_checks(checks: Sequence[Check]) -> list[Check]:
    """Checks worth an email: alert and fail, plus spend past the alert line (budget near the cap)."""
    return [c for c in checks if SEVERITY[c.status] >= SEVERITY["alert"] or (c.name == "spend" and c.status == "warn")]


def alerts(checks: Sequence[Check]) -> list[str]:
    """Lines worth an email (see alert_checks)."""
    return [f"{c.name}: {c.detail}" for c in alert_checks(checks)]


def _key(line: str) -> str:
    return hashlib.sha1(line.encode()).hexdigest()[:12]


def notify_alerts(*, now: datetime | None = None) -> dict[str, Any]:
    """Email new alerts once per IST day (Step 14.7) to everyone opted into alerts. Quiet without a Resend key."""
    from . import emails

    now = now or datetime.now(UTC)
    worth = alert_checks(collect(now=now))
    lines = [f"{c.name}: {c.detail}" for c in worth]
    day = now.astimezone(fmt.IST).date().isoformat()
    sent = db.get_setting(ALERTS_KEY, {}) or {}
    seen = set(sent.get("keys", [])) if sent.get("day") == day else set()
    new = [(c, ln) for c, ln in zip(worth, lines, strict=True) if _key(ln) not in seen]
    emailed = False
    if new and notify.email_configured():
        items = [emails.alert_item(c.name, c.status, c.detail) for c, _ in new]
        emailed = emails.send_alerts(items) > 0
        if emailed:
            db.set_setting(ALERTS_KEY, {"day": day, "keys": sorted(seen | {_key(ln) for _, ln in new})})
    return {"alerts": lines, "new": [ln for _, ln in new], "emailed": emailed}
