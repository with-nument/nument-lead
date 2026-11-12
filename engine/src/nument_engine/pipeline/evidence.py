"""Evidence shared by Steps 10 to 12: verified facts, active signals and usable contacts.

Scoring and messages only ever read facts that passed verification (Step 10.2.4). `verified_facts()` holds
that filter in one place. It returns every verified row, not only the latest per field like the app's
`v_verified_facts` view, because lists (phones, prices, services, decision makers) need all their rows.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit

from psycopg import Connection

from .. import db

Row = dict[str, Any]

CODE_MODELS: Final = frozenset({"rule", "code"})  # facts made by code (A.13.2; Step 9 also writes 'code')
GOOGLE_LISTING_MAX_AGE: Final = timedelta(days=30)  # Places terms (A.4.4, Step 10.3.4)

FACT_COLUMNS: Final = (
    "id, business_id, field, value, quote, url, page_id, model, verified, verify_score, verified_at, created_at"
)
SIGNAL_COLUMNS: Final = (
    "id, business_id, type, category, points, observed_at, expires_at, source, url, quote, details, created_at"
)
CONTACT_COLUMNS: Final = (
    "id, business_id, name, role, phone_e164, phone_type, email, source, source_url, quote, "
    "is_decision_maker, verified, verified_at, do_not_contact, created_at"
)


def _str_ids(rows: list[Row], *keys: str) -> list[Row]:
    for r in rows:
        for k in keys:
            if r.get(k) is not None:
                r[k] = str(r[k])
    return rows


def _group(rows: Iterable[Row], key: str = "business_id") -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        out[str(r[key])].append(r)
    return out


def verified_facts(business_ids: Sequence[str], *, conn: Connection[Any] | None = None) -> dict[str, list[Row]]:
    """Verified facts per business that did not lose a conflict (verify_score -1), newest first per field."""
    if not business_ids:
        return {}
    rows = db.fetch_all(
        f"select {FACT_COLUMNS} from public.facts "
        "where business_id = any(%s::uuid[]) and verified and coalesce(verify_score, 0) >= 0 "
        "order by business_id, field, created_at desc",
        [list(business_ids)],
        conn=conn,
    )
    return _group(_str_ids(rows, "id", "business_id", "page_id"))


def all_facts(business_ids: Sequence[str], *, conn: Connection[Any] | None = None) -> dict[str, list[Row]]:
    """Every fact per business, verified or not (verification itself needs them all)."""
    if not business_ids:
        return {}
    rows = db.fetch_all(
        f"select {FACT_COLUMNS} from public.facts where business_id = any(%s::uuid[]) order by created_at",
        [list(business_ids)],
        conn=conn,
    )
    return _group(_str_ids(rows, "id", "business_id", "page_id"))


def signals_for(business_ids: Sequence[str], *, conn: Connection[Any] | None = None) -> dict[str, list[Row]]:
    """Every signal per business; callers keep the active ones with `is_active`."""
    if not business_ids:
        return {}
    rows = db.fetch_all(
        f"select {SIGNAL_COLUMNS} from public.signals where business_id = any(%s::uuid[]) order by observed_at",
        [list(business_ids)],
        conn=conn,
    )
    for r in rows:
        r["points"] = float(r["points"] or 0)
        r["details"] = r.get("details") or {}
    return _group(_str_ids(rows, "id", "business_id"))


def contacts_for(business_ids: Sequence[str], *, conn: Connection[Any] | None = None) -> dict[str, list[Row]]:
    if not business_ids:
        return {}
    rows = db.fetch_all(
        f"select {CONTACT_COLUMNS} from public.contacts where business_id = any(%s::uuid[]) order by created_at",
        [list(business_ids)],
        conn=conn,
    )
    return _group(_str_ids(rows, "id", "business_id"))


def businesses(business_ids: Sequence[str], *, conn: Connection[Any] | None = None) -> dict[str, Row]:
    if not business_ids:
        return {}
    rows = db.fetch_all("select * from public.businesses where id = any(%s::uuid[])", [list(business_ids)], conn=conn)
    return {str(r["id"]): r for r in _str_ids(rows, "id")}


def is_active(signal: Mapping[str, Any], now: datetime) -> bool:
    """Active while now < expires_at (Step 10.6)."""
    expires = signal.get("expires_at")
    return expires is not None and now < expires


# ---------------------------------------------------------------------------
# Fact values (shapes from the Step 9.14 flattening table)
# ---------------------------------------------------------------------------


def vget(value: Any, *keys: str) -> Any:
    """The first present key of a dict value, or the value itself when it is a scalar."""
    if isinstance(value, Mapping):
        for k in keys:
            if value.get(k) is not None:
                return value[k]
        return None
    return value


def fact_count(fact: Mapping[str, Any]) -> int | None:
    raw = vget(fact.get("value"), "count", "value")
    try:
        return int(float(raw)) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        return None


def fact_flag(fact: Mapping[str, Any]) -> bool | None:
    """Boolean facts: {"value": true}. Also reads 'yes'/'no' strings the Appendix A prompt allows."""
    raw = vget(fact.get("value"), "value")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in {"true", "yes", "y"}:
            return True
        if low in {"false", "no", "n"}:
            return False
    return None


def fact_text(fact: Mapping[str, Any]) -> str:
    """Readable text of a fact value, for keyword checks and claim checks."""
    value = fact.get("value")
    if isinstance(value, Mapping):
        return " ".join(str(v) for v in value.values() if v is not None and not isinstance(v, Mapping | list))
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.append(" ".join(str(v) for v in item.values()) if isinstance(item, Mapping) else str(item))
        return " ".join(parts)
    return "" if value is None else str(value)


def by_field(facts: Iterable[Row], *fields: str) -> list[Row]:
    wanted = set(fields)
    return [f for f in facts if f.get("field") in wanted]


# ---------------------------------------------------------------------------
# URLs and hashes
# ---------------------------------------------------------------------------


def host_of(url: str | None) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def on_domain(url: str | None, web_domain: str | None) -> bool:
    """True when the URL's host is the business's own registrable domain or a sub-domain of it."""
    if not web_domain:
        return False
    host, dom = host_of(url), web_domain.lower().removeprefix("www.")
    return bool(host) and (host == dom or host.endswith("." + dom))


def canonical_url(url: str | None) -> str:
    """Scheme, www and trailing slash do not matter when matching a page to a URL."""
    parts = urlsplit((url or "").strip())
    path = parts.path.rstrip("/")
    return f"{host_of(url)}{path}{'?' + parts.query if parts.query else ''}".lower()


def short_id(value: Any) -> str:
    """First 4 characters of an id, for readable reasons such as 'branches_count=3 (fact 8f2c)'."""
    return str(value).replace("-", "")[:4]


def basis_hash(fact_ids: Iterable[str], signal_ids: Iterable[str], *extra: Any) -> str:
    """A short hash of the evidence a decision was based on (judge skip rule 11.10.1, message rewrite 12.11)."""
    h = hashlib.sha1(usedforsecurity=False)
    for part in sorted(str(i) for i in fact_ids):
        h.update(b"f" + part.encode())
    for part in sorted(str(i) for i in signal_ids):
        h.update(b"s" + part.encode())
    for part in extra:
        h.update(b"x" + str(part).encode())
    return h.hexdigest()[:16]


_ID_PREFIX = re.compile(r"^\[?\s*([fsFS])\s*[:#-]?\s*")


def resolve_cited_id(raw: str, known: Mapping[str, str]) -> str | None:
    """Map an id as the model wrote it ('F8f2c...', '[S1a2b...]', '8F2C...') to a known id, or None.

    `known` maps lowercase ids to the canonical id. Prompts show ids as [F<id>] and [S<id>] (Appendix A).
    """
    text = (raw or "").strip().strip("[]").strip()
    low = text.lower()
    if low in known:
        return known[low]
    m = _ID_PREFIX.match(text)
    if m:
        rest = text[m.end() :].strip().strip("[]").lower()
        if rest in known:
            return known[rest]
    return None
