"""Sending windows in the recipient's local time (contract 4.6, lane E5a).

An email goes out only on a weekday inside one of the windows in config/outreach.yaml (08:30 to 11:30 and
13:30 to 16:30), in the recipient's own time zone: the zone of the business's city when we know it, else the
country's main zone. Every calculation is done on the local wall clock and converted to UTC at the end, so a
daylight-saving change never moves a window by an hour.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

Window = tuple[time, time]

# The zone where most of a country's businesses keep office hours. Blocked countries are listed too, so allowing
# one later (a founder decision in config/outreach.yaml) needs no code change. A country missing here is never
# mailed: without a time zone there is no safe window.
COUNTRY_ZONES: Final[dict[str, str]] = {
    "in": "Asia/Kolkata",
    "ae": "Asia/Dubai",
    "us": "America/New_York",
    "gb": "Europe/London",
    "ie": "Europe/Dublin",
    "nl": "Europe/Amsterdam",
    "fr": "Europe/Paris",
    "se": "Europe/Stockholm",
    "fi": "Europe/Helsinki",
    "be": "Europe/Brussels",
    "pt": "Europe/Lisbon",
    "au": "Australia/Sydney",
    "nz": "Pacific/Auckland",
    "ca": "America/Toronto",
    "sg": "Asia/Singapore",
    "br": "America/Sao_Paulo",
    "mx": "America/Mexico_City",
    "ph": "Asia/Manila",
    "my": "Asia/Kuala_Lumpur",
    "id": "Asia/Jakarta",
    "de": "Europe/Berlin",
    "at": "Europe/Vienna",
    "dk": "Europe/Copenhagen",
    "it": "Europe/Rome",
    "es": "Europe/Madrid",
    "pl": "Europe/Warsaw",
    "il": "Asia/Jerusalem",
    "za": "Africa/Johannesburg",
    "vn": "Asia/Ho_Chi_Minh",
    "sa": "Asia/Riyadh",
    "qa": "Asia/Qatar",
    "ch": "Europe/Zurich",
    "no": "Europe/Oslo",
    "ee": "Europe/Tallinn",
    "lu": "Europe/Luxembourg",
    "hk": "Asia/Hong_Kong",
    "jp": "Asia/Tokyo",
    "kr": "Asia/Seoul",
    "th": "Asia/Bangkok",
    "ng": "Africa/Lagos",
    "ke": "Africa/Nairobi",
    "eg": "Africa/Cairo",
    "ar": "America/Argentina/Buenos_Aires",
    "cl": "America/Santiago",
    "co": "America/Bogota",
}

_EASTERN, _CENTRAL, _MOUNTAIN, _PACIFIC = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"

# Countries that span several zones: their main startup cities.
CITY_ZONES: Final[dict[str, dict[str, str]]] = {
    "us": {
        **dict.fromkeys(
            [
                "new york",
                "new york city",
                "nyc",
                "brooklyn",
                "manhattan",
                "boston",
                "cambridge",
                "somerville",
                "washington",
                "philadelphia",
                "pittsburgh",
                "atlanta",
                "miami",
                "orlando",
                "tampa",
                "jacksonville",
                "charlotte",
                "raleigh",
                "durham",
                "baltimore",
                "detroit",
                "ann arbor",
                "columbus",
                "cleveland",
                "cincinnati",
                "indianapolis",
                "newark",
                "jersey city",
                "hoboken",
                "providence",
                "richmond",
                "stamford",
                "new haven",
                "burlington",
                "louisville",
            ],
            _EASTERN,
        ),
        **dict.fromkeys(
            [
                "chicago",
                "austin",
                "dallas",
                "houston",
                "san antonio",
                "fort worth",
                "plano",
                "minneapolis",
                "st louis",
                "saint louis",
                "kansas city",
                "nashville",
                "memphis",
                "new orleans",
                "milwaukee",
                "madison",
                "oklahoma city",
                "tulsa",
                "omaha",
                "des moines",
                "birmingham",
                "little rock",
            ],
            _CENTRAL,
        ),
        **dict.fromkeys(["denver", "boulder", "salt lake city", "provo", "lehi", "albuquerque", "boise"], _MOUNTAIN),
        **dict.fromkeys(["phoenix", "scottsdale", "tempe", "mesa", "chandler", "tucson"], "America/Phoenix"),
        **dict.fromkeys(
            [
                "san francisco",
                "sf",
                "palo alto",
                "mountain view",
                "menlo park",
                "san jose",
                "oakland",
                "berkeley",
                "sunnyvale",
                "santa clara",
                "cupertino",
                "redwood city",
                "san mateo",
                "los angeles",
                "santa monica",
                "venice",
                "pasadena",
                "irvine",
                "san diego",
                "sacramento",
                "seattle",
                "bellevue",
                "redmond",
                "portland",
                "las vegas",
                "reno",
            ],
            _PACIFIC,
        ),
        "honolulu": "Pacific/Honolulu",
        "anchorage": "America/Anchorage",
        "san juan": "America/Puerto_Rico",
    },
    "ca": {
        **dict.fromkeys(["toronto", "ottawa", "montreal", "quebec", "waterloo", "kitchener"], "America/Toronto"),
        **dict.fromkeys(["vancouver", "victoria", "burnaby", "surrey"], "America/Vancouver"),
        **dict.fromkeys(["calgary", "edmonton"], "America/Edmonton"),
        "winnipeg": "America/Winnipeg",
        **dict.fromkeys(["regina", "saskatoon"], "America/Regina"),
        "halifax": "America/Halifax",
        "st johns": "America/St_Johns",
    },
    "au": {
        **dict.fromkeys(["sydney", "canberra", "newcastle"], "Australia/Sydney"),
        **dict.fromkeys(["melbourne", "geelong"], "Australia/Melbourne"),
        **dict.fromkeys(["brisbane", "gold coast", "sunshine coast"], "Australia/Brisbane"),
        **dict.fromkeys(["perth", "fremantle"], "Australia/Perth"),
        "adelaide": "Australia/Adelaide",
        **dict.fromkeys(["hobart", "launceston"], "Australia/Hobart"),
        "darwin": "Australia/Darwin",
    },
    "br": {
        "manaus": "America/Manaus",
        "cuiaba": "America/Cuiaba",
        "campo grande": "America/Campo_Grande",
        "porto velho": "America/Porto_Velho",
        "rio branco": "America/Rio_Branco",
    },
    "mx": {
        **dict.fromkeys(["tijuana", "mexicali", "ensenada"], "America/Tijuana"),
        "hermosillo": "America/Hermosillo",
        **dict.fromkeys(["cancun", "playa del carmen", "tulum"], "America/Cancun"),
        "chihuahua": "America/Chihuahua",
        **dict.fromkeys(["mazatlan", "la paz"], "America/Mazatlan"),
    },
    "id": {
        **dict.fromkeys(["bali", "denpasar", "makassar", "balikpapan"], "Asia/Makassar"),
        **dict.fromkeys(["jayapura", "ambon"], "Asia/Jayapura"),
    },
    "nz": {"chatham": "Pacific/Chatham"},
}

# States, provinces and territories (codes and names), read after a comma ("Austin, TX") or in an address.
REGION_ZONES: Final[dict[str, dict[str, str]]] = {
    "us": {
        **dict.fromkeys(
            [
                "ct",
                "connecticut",
                "de",
                "delaware",
                "dc",
                "district of columbia",
                "fl",
                "florida",
                "ga",
                "georgia",
                "in",
                "indiana",
                "ky",
                "kentucky",
                "me",
                "maine",
                "md",
                "maryland",
                "ma",
                "massachusetts",
                "mi",
                "michigan",
                "nh",
                "new hampshire",
                "nj",
                "new jersey",
                "ny",
                "new york",
                "nc",
                "north carolina",
                "oh",
                "ohio",
                "pa",
                "pennsylvania",
                "ri",
                "rhode island",
                "sc",
                "south carolina",
                "vt",
                "vermont",
                "va",
                "virginia",
                "wv",
                "west virginia",
            ],
            _EASTERN,
        ),
        **dict.fromkeys(
            [
                "al",
                "alabama",
                "ar",
                "arkansas",
                "il",
                "illinois",
                "ia",
                "iowa",
                "ks",
                "kansas",
                "la",
                "louisiana",
                "mn",
                "minnesota",
                "ms",
                "mississippi",
                "mo",
                "missouri",
                "ne",
                "nebraska",
                "nd",
                "north dakota",
                "ok",
                "oklahoma",
                "sd",
                "south dakota",
                "tn",
                "tennessee",
                "tx",
                "texas",
                "wi",
                "wisconsin",
            ],
            _CENTRAL,
        ),
        **dict.fromkeys(
            ["co", "colorado", "id", "idaho", "mt", "montana", "nm", "new mexico", "ut", "utah", "wy", "wyoming"],
            _MOUNTAIN,
        ),
        **dict.fromkeys(["az", "arizona"], "America/Phoenix"),
        **dict.fromkeys(["ca", "california", "nv", "nevada", "or", "oregon", "wa", "washington"], _PACIFIC),
        **dict.fromkeys(["hi", "hawaii"], "Pacific/Honolulu"),
        **dict.fromkeys(["ak", "alaska"], "America/Anchorage"),
        **dict.fromkeys(["pr", "puerto rico"], "America/Puerto_Rico"),
    },
    "ca": {
        **dict.fromkeys(["on", "ontario", "qc", "quebec"], "America/Toronto"),
        **dict.fromkeys(["bc", "british columbia"], "America/Vancouver"),
        **dict.fromkeys(["ab", "alberta"], "America/Edmonton"),
        **dict.fromkeys(["mb", "manitoba"], "America/Winnipeg"),
        **dict.fromkeys(["sk", "saskatchewan"], "America/Regina"),
        **dict.fromkeys(["ns", "nova scotia", "nb", "new brunswick", "pe", "prince edward island"], "America/Halifax"),
        **dict.fromkeys(["nl", "newfoundland and labrador", "newfoundland"], "America/St_Johns"),
    },
    "au": {
        **dict.fromkeys(["nsw", "new south wales", "act"], "Australia/Sydney"),
        **dict.fromkeys(["vic", "victoria"], "Australia/Melbourne"),
        **dict.fromkeys(["qld", "queensland"], "Australia/Brisbane"),
        **dict.fromkeys(["wa", "western australia"], "Australia/Perth"),
        **dict.fromkeys(["sa", "south australia"], "Australia/Adelaide"),
        **dict.fromkeys(["tas", "tasmania"], "Australia/Hobart"),
        **dict.fromkeys(["nt", "northern territory"], "Australia/Darwin"),
    },
}

# Region codes as they appear in a postal address: "Austin, TX 78701", "Toronto ON M5V 2T6", "Sydney NSW 2000".
_ADDRESS_REGION: Final[dict[str, re.Pattern[str]]] = {
    "us": re.compile(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b"),
    "ca": re.compile(r"\b(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\s+[A-Z]\d[A-Z]\b"),
    "au": re.compile(r"\b(NSW|VIC|QLD|WA|SA|TAS|NT|ACT)\s+\d{4}\b"),
}
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")
WEEKDAYS_ONLY: Final = 5  # Monday to Friday: weekday() 0 to 4


def _norm(text: str) -> str:
    """Lower case, accents and punctuation removed: "São Paulo" is "sao paulo", "St. Louis" is "st louis"."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return _SPACES.sub(" ", _NON_WORD.sub(" ", plain)).strip()


def zone_for(country: str | None, city: str | None = None, address: str | None = None) -> ZoneInfo | None:
    """The recipient's time zone: the city, then a state or region after a comma ("Austin, TX"), then a region
    code in the postal address, then the country's main zone. None for a country we have no zone for (it is
    never mailed)."""
    code = (country or "").strip().lower()
    if code not in COUNTRY_ZONES:
        return None
    cities, regions = CITY_ZONES.get(code, {}), REGION_ZONES.get(code, {})
    parts = [p for p in (_norm(part) for part in (city or "").split(",")) if p]
    if parts:
        first, rest = parts[0], parts[1:]
        found = cities.get(first) or regions.get(first)
        for part in rest:
            found = found or regions.get(part) or cities.get(part)
        if found:
            return ZoneInfo(found)
    if address and code in _ADDRESS_REGION:
        for match in _ADDRESS_REGION[code].finditer(address):
            region = regions.get(match.group(1).lower())
            if region:
                return ZoneInfo(region)
    return ZoneInfo(COUNTRY_ZONES[code])


def parse_windows(raw: Sequence[Sequence[Any]]) -> tuple[Window, ...]:
    """config/outreach.yaml `windows` ([["08:30", "11:30"], ...]) as sorted (start, end) local times."""
    windows: list[Window] = []
    for pair in raw:
        if len(pair) != 2:
            raise ValueError(f"a sending window needs a start and an end, got {pair!r}")
        start, end = (time.fromisoformat(str(v)) for v in pair)
        if not start < end:
            raise ValueError(f"a sending window must start before it ends, got {pair!r}")
        windows.append((start, end))
    return tuple(sorted(windows))


def config_windows() -> tuple[Window, ...]:
    """The weekday sending windows from config/outreach.yaml."""
    from .net import outreach_config

    return parse_windows(outreach_config().get("windows") or [])


def in_window(at: datetime, zone: ZoneInfo, windows: Sequence[Window]) -> bool:
    """True when `at` falls on a weekday inside a window, on the recipient's local clock."""
    local = at.astimezone(zone)
    if local.weekday() >= WEEKDAYS_ONLY:
        return False
    now = local.time()
    return any(start <= now < end for start, end in windows)


def _at_local(day: Any, clock: time, zone: ZoneInfo) -> datetime:
    """A local wall-clock time as an absolute UTC time. A time skipped by a daylight-saving jump comes out
    moved forward by the jump; a repeated time is its first occurrence."""
    return datetime.combine(day, clock, tzinfo=zone).astimezone(UTC)


def next_window_start(at: datetime, zone: ZoneInfo, windows: Sequence[Window]) -> datetime:
    """`at` itself (in UTC) when it is inside a window, else the start of the next window."""
    if in_window(at, zone, windows):
        return at.astimezone(UTC)
    local = at.astimezone(zone)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() >= WEEKDAYS_ONLY:
            continue
        for start, _end in windows:
            candidate = _at_local(day, start, zone)
            if candidate > at:
                return candidate
    raise ValueError("no sending window configured")


def followup_at(sent_at: datetime, days: int, zone: ZoneInfo, windows: Sequence[Window]) -> datetime:
    """When a follow-up `days` after `sent_at` goes out: the same local clock time that many calendar days
    later (not days times 24 hours, which drifts by an hour across a daylight-saving change), moved into the
    next window."""
    local = sent_at.astimezone(zone)
    target = (local.replace(tzinfo=None) + timedelta(days=days)).replace(tzinfo=zone)
    return next_window_start(target, zone, windows)
