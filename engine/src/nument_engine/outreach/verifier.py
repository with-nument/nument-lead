"""Email checks without sending anything (founder approved, 15 Nov 2026): two free verification APIs over HTTPS.

GitHub Actions blocks port 25, so the engine never talks SMTP itself. QuickEmailVerification (primary, 100 free
checks a day) and MyEmailVerifier (backup, 100 a day) say whether a mailbox exists; no email is ever sent.

- Only `outreach/net.py` clients call them: allowed hosts only, https only, proxies ignored.
- Every answer becomes one result: deliverable, undeliverable, risky or unknown, plus a catch-all flag (the
  domain accepts any address, so one mailbox cannot be confirmed). Deliverable is strict: the provider says the
  mailbox exists, the domain is known not to be catch-all, and the address is not disposable or role based
  (QuickEmailVerification must also say safe_to_send). Anything less is risky, never deliverable.
- 429, a spent quota or a refused key moves on to the other provider. A provider whose daily quota ran out is
  remembered for the rest of the IST day (settings `email_check.exhausted.<provider>`).
- Answers are cached in `email_checks`: 30 days, but an inconclusive "unknown" only one day (the providers say
  to retry those later). A catch-all answer is stored for the domain in `email_domains`.
- Daily caps: `email_check.per_day` (150) across both providers, and each provider's free quota
  (`email_check.qev_per_day`, `email_check.mev_per_day`: 100 each), counted from today's `email_checks` rows.
- An API key never reaches a log or a table: QuickEmailVerification takes it as a query parameter and
  MyEmailVerifier in the path, so no URL of these calls is logged, stored or chained into an error; only the
  answer's own fields are kept.

`run` is the outreach phase `verify_emails`: the address of every open thread with a step due within 24 hours is
checked again when it was last checked more than 30 days ago (or never), before anything goes out.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Self
from urllib.parse import quote

import httpx
from psycopg import Connection

from .. import db
from ..budget import ist_day_start, ist_today
from ..logging import get_logger
from ..pipeline.runs import RunContext, outreach_mode
from ..settings import get_settings
from . import net

log = get_logger()

Result = Literal["deliverable", "undeliverable", "risky", "unknown"]
RESULTS: Final[tuple[str, ...]] = ("deliverable", "undeliverable", "risky", "unknown")
ErrorKind = Literal["quota", "rate_limited", "auth", "transient", "malformed"]

QEV: Final = "quickemailverification"
MEV: Final = "myemailverifier"
QEV_URL: Final = "https://api.quickemailverification.com/v1/verify"
MEV_URL: Final = "https://client.myemailverifier.com/verifier/validate_single"

CACHE_DAYS: Final = 30
UNKNOWN_TTL: Final = timedelta(days=1)
DEFAULT_PER_DAY: Final = 150
DEFAULT_PROVIDER_PER_DAY: Final = 100
PROVIDER_SETTING: Final[dict[str, str]] = {QEV: "email_check.qev_per_day", MEV: "email_check.mev_per_day"}
MAX_TRANSIENT: Final = 3  # failures in a row before a provider is left alone for the rest of the run
DUE_LIMIT: Final = 200

# Where an address came from (contacts.email_origin). These were read on a page (or a record) the person or the
# company published; snippet (a search answer we could not read ourselves) and guess are not.
PUBLISHED_ORIGINS: Final = frozenset({"published", "archive", "store", "filing", "post"})

QEV_KEEP: Final = ("result", "reason", "accept_all", "disposable", "role", "free", "safe_to_send", "mx_domain")
MEV_KEEP: Final = ("Status", "catch_all", "Disposable_Domain", "Role_Based", "Free_Domain", "Greylisted", "Diagnosis")
MEV_QUOTA: Final = frozenset({"INSUFFICIENT_CREDITS"})
MEV_AUTH: Final = frozenset(
    {"INVALID_API_KEY", "UNAUTHORIZED_REFERER", "DEMO_KEY_NOT_ALLOWED", "ACCOUNT_BLOCKED",
     "PAYMENT_VERIFICATION_REQUIRED"}
)  # fmt: skip


class VerifierError(Exception):
    """One provider could not answer for one address. `kind` decides what happens next (see Verifier)."""

    def __init__(self, provider: str, kind: ErrorKind, detail: str = "", status: int | None = None) -> None:
        super().__init__(f"{provider}: {kind}" + (f" ({detail})" if detail else ""))
        self.provider = provider
        self.kind: ErrorKind = kind
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class Check:
    """One answer about one address."""

    email: str
    result: Result
    catch_all: bool | None  # True: the domain accepts every address; None: the answer does not say
    provider: str
    raw: dict[str, Any]  # the provider's answer fields we keep (never a URL, never a key)
    checked_at: datetime
    cached: bool = False

    @property
    def deliverable(self) -> bool:
        """The mailbox exists and the domain is known not to accept every address."""
        return self.result == "deliverable" and self.catch_all is False


def flag(value: Any) -> bool | None:
    """The providers send flags as "true"/"false" strings; None when a flag is missing or unreadable."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _kept(body: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {k: body[k] for k in keys if k in body and isinstance(body[k], str | bool | int | float)}


def parse_qev(status: int, body: Any) -> tuple[Result, bool | None, dict[str, Any]]:
    """(result, catch_all, kept fields) from one QuickEmailVerification answer; raises VerifierError.

    Documented codes: 402 out of credits, 401 bad key, 403 account disabled, 429 rate limit. A 200 with
    success "false" carries a message such as "Low credit. Payment required"."""
    if status == 402:
        raise VerifierError(QEV, "quota", "out of credits", status)
    if status in (401, 403):
        raise VerifierError(QEV, "auth", f"http {status}", status)
    if status == 429:
        raise VerifierError(QEV, "rate_limited", "http 429", status)
    if status >= 500:
        raise VerifierError(QEV, "transient", f"http {status}", status)
    if status != 200 or not isinstance(body, Mapping):
        raise VerifierError(QEV, "malformed", f"http {status}", status)
    if flag(body.get("success")) is False:
        message = str(body.get("message") or "").lower()
        if "credit" in message or "payment" in message:
            raise VerifierError(QEV, "quota", "low credit", status)
        if "ip address" in message or "not allowed" in message or "api key" in message:
            raise VerifierError(QEV, "auth", "refused", status)
        raise VerifierError(QEV, "malformed", "refused", status)
    kept = _kept(body, QEV_KEEP)
    result = str(body.get("result") or "").strip().lower()
    accept_all = flag(body.get("accept_all"))
    if result == "valid":
        if accept_all:
            return "risky", True, kept
        clean = flag(body.get("disposable")) is False and flag(body.get("role")) is not True
        if accept_all is False and flag(body.get("safe_to_send")) is True and clean:
            return "deliverable", False, kept
        return "risky", accept_all, kept
    if result == "invalid":
        # a server that rejects one mailbox does not accept every address
        rejected = str(body.get("reason") or "").strip().lower() == "rejected_email"
        return "undeliverable", (False if rejected else None), kept
    if result == "unknown":
        return "unknown", (True if accept_all else None), kept
    raise VerifierError(QEV, "malformed", "unexpected result", status)


def parse_mev(status: int, body: Any) -> tuple[Result, bool | None, dict[str, Any]]:
    """(result, catch_all, kept fields) from one MyEmailVerifier answer; raises VerifierError.

    Documented errors: {"status": false, "error": "RATE_LIMIT_EXCEEDED" | "INSUFFICIENT_CREDITS" |
    "INVALID_API_KEY" | ...}. Status is Valid, Invalid, Catch-all or Unknown."""
    error = str(body.get("error") or "").strip().upper() if isinstance(body, Mapping) else ""
    if status == 429 or error == "RATE_LIMIT_EXCEEDED":
        raise VerifierError(MEV, "rate_limited", "rate limit", status)
    if status == 402 or error in MEV_QUOTA:
        raise VerifierError(MEV, "quota", "out of credits", status)
    if status in (401, 403) or error in MEV_AUTH:
        raise VerifierError(MEV, "auth", error.lower() or f"http {status}", status)
    if status >= 500 or error == "SERVER_ERROR":
        raise VerifierError(MEV, "transient", f"http {status}", status)
    if status != 200 or not isinstance(body, Mapping):
        raise VerifierError(MEV, "malformed", f"http {status}", status)
    if "Status" not in body and flag(body.get("status")) is False:
        message = str(body.get("message") or body.get("msg") or "").lower()
        if "credit" in message:
            raise VerifierError(MEV, "quota", "out of credits", status)
        if "key" in message:
            raise VerifierError(MEV, "auth", "refused", status)
        raise VerifierError(MEV, "malformed", "refused", status)
    kept = _kept(body, MEV_KEEP)
    state = re.sub(r"[^a-z]", "", str(body.get("Status") or "").lower())
    catch_all = flag(body.get("catch_all"))
    if state == "catchall" or catch_all:
        return "risky", True, kept
    if state == "valid":
        if flag(body.get("Greylisted")):
            return "unknown", catch_all, kept
        clean = flag(body.get("Disposable_Domain")) is not True and flag(body.get("Role_Based")) is not True
        if catch_all is False and clean:
            return "deliverable", False, kept
        return "risky", catch_all, kept
    if state in ("invalid", "spamtrap"):
        return "undeliverable", None, kept
    if state in ("unknown", "greylisted", "greylist"):
        return "unknown", catch_all, kept
    if state == "disposable":
        return "risky", catch_all, kept
    raise VerifierError(MEV, "malformed", "unexpected status", status)


class Provider:
    """One verification API. The key lives here only; it is never part of a repr, a log line or an error."""

    name: str = ""

    def __init__(self, key: str) -> None:
        self._key = key

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    def send(self, client: httpx.Client, email: str) -> httpx.Response:
        raise NotImplementedError

    def parse(self, status: int, body: Any) -> tuple[Result, bool | None, dict[str, Any]]:
        raise NotImplementedError


class QuickEmailVerification(Provider):
    name = QEV

    def send(self, client: httpx.Client, email: str) -> httpx.Response:
        return client.get(QEV_URL, params={"email": email, "apikey": self._key})

    def parse(self, status: int, body: Any) -> tuple[Result, bool | None, dict[str, Any]]:
        return parse_qev(status, body)


class MyEmailVerifier(Provider):
    name = MEV

    def send(self, client: httpx.Client, email: str) -> httpx.Response:
        return client.get(f"{MEV_URL}/{quote(email, safe='@')}/{quote(self._key, safe='')}")

    def parse(self, status: int, body: Any) -> tuple[Result, bool | None, dict[str, Any]]:
        return parse_mev(status, body)


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


def _now() -> datetime:
    return datetime.now(UTC)


class Verifier:
    """Checks addresses with the first provider that can answer and caches every answer.

    One instance per stage run: it remembers which providers failed during the run. Use as a context manager
    (or call `close`) so the HTTP client is closed."""

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.providers = list(providers)
        self.transport = transport
        self.clock = clock
        self.stats: Counter[str] = Counter()
        self.off: dict[str, str] = {}  # provider -> why it is not used again in this run
        self._failures: Counter[str] = Counter()
        self._client: httpx.Client | None = None

    @classmethod
    def from_settings(cls, *, transport: httpx.BaseTransport | None = None) -> Verifier:
        """QuickEmailVerification first, then MyEmailVerifier: each one only when its key is set."""
        settings = get_settings()
        providers: list[Provider] = []
        if settings.qev_api_key is not None and settings.qev_api_key.get_secret_value():
            providers.append(QuickEmailVerification(settings.qev_api_key.get_secret_value()))
        if settings.mev_api_key is not None and settings.mev_api_key.get_secret_value():
            providers.append(MyEmailVerifier(settings.mev_api_key.get_secret_value()))
        return cls(providers, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- cache and caps ----------------------------------------------------------------------------
    def cached(self, email: str) -> Check | None:
        """The stored answer for an address while it is fresh (30 days; an "unknown" answer one day)."""
        row = db.fetch_one(
            "select email, result, provider, raw, checked_at from public.email_checks where email = %s",
            [email.strip().lower()],
        )
        if row is None:
            return None
        ttl = UNKNOWN_TTL if row["result"] == "unknown" else timedelta(days=CACHE_DAYS)
        if self.clock() - row["checked_at"] > ttl:
            return None
        raw = row["raw"] if isinstance(row["raw"], dict) else {}
        catch_all = raw.get("catch_all")
        return Check(
            email=str(row["email"]),
            result=row["result"],
            catch_all=catch_all if isinstance(catch_all, bool) else None,
            provider=str(row["provider"]),
            raw=dict(raw.get("fields") or {}),
            checked_at=row["checked_at"],
            cached=True,
        )

    def _used_today(self, provider: str | None = None) -> int:
        value = db.scalar(
            "select count(*) from public.email_checks where checked_at >= %s and (%s::text is null or provider = %s)",
            [ist_day_start(self.clock()), provider, provider],
        )
        return int(value or 0)

    def room(self) -> int:
        """Live checks still allowed today across both providers (settings email_check.per_day)."""
        per_day = int(db.get_setting("email_check.per_day", DEFAULT_PER_DAY) or 0)
        return max(per_day - self._used_today(), 0)

    def _provider_ready(self, provider: Provider) -> bool:
        if provider.name in self.off:
            return False
        if db.get_setting(f"email_check.exhausted.{provider.name}") == ist_today(self.clock()).isoformat():
            self.off[provider.name] = "quota"
            return False
        per_day = int(db.get_setting(PROVIDER_SETTING.get(provider.name, ""), DEFAULT_PROVIDER_PER_DAY) or 0)
        if self._used_today(provider.name) >= per_day:
            self.off[provider.name] = "daily_cap"
            return False
        return True

    def available(self) -> bool:
        """Could a live check run now (a key, a provider with quota left, room under the daily cap)?"""
        return any(self._provider_ready(p) for p in self.providers) and self.room() > 0

    # ---- checks -------------------------------------------------------------------------------------
    def check(self, email: str, *, use_cache: bool = True, reserve: int = 0) -> Check | None:
        """The answer for one address: the cached one while fresh, else a live check with the first provider
        that can answer. None when nobody can: no key, quotas or the daily cap spent (keeping `reserve` checks
        for later), or every provider failing."""
        email = email.strip().lower()
        if use_cache:
            hit = self.cached(email)
            if hit is not None:
                self.stats["cached"] += 1
                return hit
        if not self.providers:
            self.stats["not_configured"] += 1
            return None
        if self.room() <= reserve:
            self.stats["capped"] += 1
            return None
        for provider in self.providers:
            if not self._provider_ready(provider):
                continue
            try:
                result, catch_all, kept = self._ask(provider, email)
            except VerifierError as err:
                self._failed(provider, err)
                continue
            self._failures[provider.name] = 0
            answer = Check(email, result, catch_all, provider.name, kept, self.clock())
            self._store(answer)
            self.stats["live"] += 1
            self.stats[f"{provider.name}.{result}"] += 1
            return answer
        self.stats["no_provider"] += 1
        return None

    def _client_for(self) -> httpx.Client:
        if self._client is None:
            self._client = net.api_client(transport=self.transport)
        return self._client

    def _ask(self, provider: Provider, email: str) -> tuple[Result, bool | None, dict[str, Any]]:
        """One request. Errors are re-raised without their cause: an httpx error can carry the URL (and with it
        the key), so it never reaches a traceback, a log line or the run's stats."""
        try:
            response = provider.send(self._client_for(), email)
        except net.HostNotAllowed:
            raise VerifierError(provider.name, "auth", "host not allowed") from None
        except httpx.TimeoutException:
            raise VerifierError(provider.name, "transient", "timeout") from None
        except httpx.HTTPError as exc:
            raise VerifierError(provider.name, "transient", type(exc).__name__) from None
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        return provider.parse(response.status_code, body)

    def _failed(self, provider: Provider, err: VerifierError) -> None:
        self.stats[f"{provider.name}.{err.kind}"] += 1
        log.warning("verifier.provider_error", provider=provider.name, kind=err.kind, status=err.status)
        if err.kind == "quota":
            db.set_setting(f"email_check.exhausted.{provider.name}", ist_today(self.clock()).isoformat())
            self.off[provider.name] = "quota"
        elif err.kind in ("rate_limited", "auth"):
            self.off[provider.name] = err.kind
        else:
            self._failures[provider.name] += 1
            if self._failures[provider.name] >= MAX_TRANSIENT:
                self.off[provider.name] = "failing"

    def _store(self, answer: Check) -> None:
        with db.tx("engine", {"stage": "email_checks"}) as conn:
            conn.execute(
                "insert into public.email_checks (email, result, provider, raw, checked_at) "
                "values (%s, %s, %s, %s, %s) on conflict (email) do update set result = excluded.result, "
                "provider = excluded.provider, raw = excluded.raw, checked_at = excluded.checked_at",
                [answer.email, answer.result, answer.provider,
                 db.Jsonb({"catch_all": answer.catch_all, "fields": answer.raw}), answer.checked_at],
            )  # fmt: skip
            if answer.catch_all is not None:
                record_catch_all(domain_of(answer.email), answer.catch_all, answer.checked_at, conn=conn)


# ---------------------------------------------------------------------------------------------------
# email_domains: the mail provider and the catch-all answer per domain
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainInfo:
    domain: str
    mx_provider: str | None  # google, microsoft, zoho, other, none
    catch_all: bool | None
    checked_at: datetime


def domain_info(domain: str, *, now: datetime | None = None) -> DomainInfo | None:
    """The domain's row while it is fresher than 30 days, else None."""
    row = db.fetch_one(
        "select domain, mx_provider, catch_all, checked_at from public.email_domains where domain = %s",
        [domain.strip().lower()],
    )
    if row is None or (now or _now()) - row["checked_at"] > timedelta(days=CACHE_DAYS):
        return None
    return DomainInfo(str(row["domain"]), row["mx_provider"], row["catch_all"], row["checked_at"])


def save_domain(domain: str, mx_provider: str, *, now: datetime | None = None) -> None:
    """A fresh mail provider for the domain. The catch-all answer is reset: the next check learns it again."""
    db.execute(
        "insert into public.email_domains (domain, mx_provider, catch_all, checked_at) values (%s, %s, null, %s) "
        "on conflict (domain) do update set mx_provider = excluded.mx_provider, catch_all = null, "
        "checked_at = excluded.checked_at",
        [domain.strip().lower(), mx_provider, now or _now()],
    )


def record_catch_all(domain: str, catch_all: bool, at: datetime, *, conn: Connection[Any] | None = None) -> None:
    """What a check taught us about the domain (the row's age, and its mail provider, stay as they are)."""
    if not domain:
        return
    db.execute(
        "insert into public.email_domains (domain, catch_all, checked_at) values (%s, %s, %s) "
        "on conflict (domain) do update set catch_all = excluded.catch_all",
        [domain, catch_all, at],
        conn=conn,
    )


# ---------------------------------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------------------------------


def relabel(current: str | None, origin: str | None, answer: Check) -> str:
    """A contact's email status after a fresh check (the re-check before sending).

    verified needs a deliverable answer on a domain that is not catch-all; an undeliverable answer is invalid.
    Otherwise an address the person or company published stays likely; a guess (or an unconfirmed snippet)
    stays likely only when it was likely before (its pattern was backed by a published address) and the answer
    is not a proof against it; anything else becomes unknown, so it is never sent on its own."""
    if answer.result == "undeliverable":
        return "invalid"
    if answer.deliverable:
        return "verified"
    if origin in PUBLISHED_ORIGINS:
        return "likely"
    if current == "likely":
        return "likely"
    return "unknown"


# ---------------------------------------------------------------------------------------------------
# The outreach phase: re-check before sending
# ---------------------------------------------------------------------------------------------------

DUE_SQL: Final = """
select distinct on (c.id) c.id::text as contact_id, c.email, c.email_status, c.email_origin
  from public.email_threads t
  join public.contacts c on c.id = t.contact_id
 where t.status = 'open'
   and c.email is not null
   and lower(c.email) = lower(t.to_email)
   and not c.do_not_contact
   and c.email_status <> 'invalid'
   and (c.email_checked_at is null or c.email_checked_at < now() - make_interval(days => %(days)s))
   and exists (select 1 from public.email_messages m
                where m.thread_id = t.id and m.direction = 'out'
                  and m.status in ('draft', 'review', 'approved', 'queued')
                  and (m.scheduled_for is null or m.scheduled_for <= now() + interval '24 hours'))
 order by c.id
 limit %(limit)s
"""


def run(rc: RunContext, verifier: Verifier | None = None, **_: Any) -> dict[str, Any]:
    """`verify_emails` (outreach run): re-check the addresses due to be mailed within 24 hours and last checked
    more than 30 days ago (or never). An inconclusive answer leaves the address due, so it is tried again."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    rows = db.fetch_all(DUE_SQL, {"days": CACHE_DAYS, "limit": rc.opts.limit or DUE_LIMIT})
    stats: Counter[str] = Counter(due=len(rows))
    if rc.opts.dry_run or not rows:
        return dict(stats)
    own = verifier is None
    checker = verifier if verifier is not None else Verifier.from_settings()
    try:
        if not checker.configured:
            stats["not_configured"] = len(rows)
            return dict(stats)
        for row in rows:
            if rc.time_left() <= 0:
                stats["stopped_time"] += 1
                break
            answer = checker.check(str(row["email"]))
            if answer is None:
                stats["not_checked"] += 1
                continue
            status = relabel(row["email_status"], row["email_origin"], answer)
            checked_at = None if answer.result == "unknown" else answer.checked_at
            db.execute(
                "update public.contacts set email_status = %s, email_checked_at = coalesce(%s, email_checked_at) "
                "where id = %s",
                [status, checked_at, row["contact_id"]],
            )
            stats[f"status.{status}"] += 1
        stats.update({f"checks.{k}": v for k, v in checker.stats.items()})
    finally:
        if own:
            checker.close()
    result = dict(stats)
    log.info("verify_emails.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
