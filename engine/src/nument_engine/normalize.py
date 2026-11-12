"""Pure normalisation helpers used to compare businesses (Step 6.5): names, websites, phones, emails, URLs, places.

No database, no network: everything here is a pure function, so it is cheap to test and safe to call anywhere.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers
import tldextract

PhoneKind = Literal["mobile", "landline", "tollfree", "unknown"]

# ---------------------------------------------------------------------------------------------------
# Names (6.5.1)
# ---------------------------------------------------------------------------------------------------

LEGAL_SUFFIXES: tuple[str, ...] = (
    "private limited",
    "pvt ltd",
    "pvt",
    "ltd",
    "limited",
    "llp",
    "inc",
    "llc",
    "l l c",
    "fze",
    "fzco",
    "fz llc",
    "and co",
    "co",
    "opc",
)
_SUFFIXES_LONGEST_FIRST = sorted(LEGAL_SUFFIXES, key=len, reverse=True)  # "fz llc" before "llc"
GENERIC_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "clinic",
        "clinics",
        "centre",
        "center",
        "hospital",
        "multispeciality",
        "multispecialty",
        "academy",
        "institute",
        "realty",
        "properties",
        "real",
        "estate",
    }
)
_SPACES = re.compile(r"\s+")


def norm_name(raw: str | None) -> str:
    """Lower-case name without punctuation or legal suffixes: `Dr. Sharma's Skin & Hair Clinic Pvt. Ltd.` becomes
    `dr sharma s skin and hair clinic`. Letters and digits of every script are kept."""
    s = unicodedata.normalize("NFKC", raw or "").lower().replace("&", " and ")
    # Punctuation and symbols become spaces; letters, digits and combining marks of every script stay
    # (Devanagari vowel signs are marks, not word characters, so `\W` would break Hindi names apart).
    s = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in s)
    s = _SPACES.sub(" ", s).strip()
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES_LONGEST_FIRST:
            if s.endswith(" " + suffix):
                s, changed = s[: -len(suffix) - 1].strip(), True
    return s


def plain_text(raw: str | None) -> str:
    """Lower case, punctuation as spaces, `&` as `and`, legal suffixes kept: for matching phrases such as
    exclusion names ("dlf limited" must not shrink to "dlf", a Gurugram locality in many clinic names)."""
    s = unicodedata.normalize("NFKC", raw or "").lower().replace("&", " and ")
    s = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in s)
    return _SPACES.sub(" ", s).strip()


def compact_name(raw: str | None) -> str:
    """`norm_name` without generic words or spaces, in the original order: `Dr. Ali's Dentacare` and
    `Dralisdentacare` both become `dralisdentacare`. Used for an exact match within one city."""
    return "".join(t for t in norm_name(raw).split() if t not in GENERIC_WORDS)


def match_key(raw: str | None) -> str:
    """`norm_name` without generic words, tokens sorted: used only for fuzzy matching."""
    tokens = [t for t in norm_name(raw).split() if t not in GENERIC_WORDS]
    return " ".join(sorted(tokens))


# ---------------------------------------------------------------------------------------------------
# Websites (6.5.2)
# ---------------------------------------------------------------------------------------------------

# Not the business's own site: directories, social networks, portals and link shorteners.
IGNORED_HOSTS: frozenset[str] = frozenset(
    {
        "practo.com",
        "lybrate.com",
        "eka.care",
        "whitecoats.com",
        "clinicspots.com",
        "credihealth.com",
        "drlogy.com",
        "zoylo.com",
        "medindia.net",
        "docprime.com",
        "mfine.co",
        "1mg.com",
        "tata1mg.com",
        "bajajfinservhealth.in",
        "justdial.com",
        "sulekha.com",
        "indiamart.com",
        "facebook.com",
        "fb.com",
        "instagram.com",
        "linkedin.com",
        "x.com",
        "twitter.com",
        "youtube.com",
        "youtu.be",
        "linktr.ee",
        "wa.me",
        "whatsapp.com",
        "google.com",
        "goo.gl",
        "g.page",
        "g.co",
        "bit.ly",
        "magicbricks.com",
        "99acres.com",
        "housing.com",
        "nobroker.in",
        "bayut.com",
        "propertyfinder.ae",
        "dubizzle.com",
        "shiksha.com",
        "collegedunia.com",
        "zomato.com",
        "swiggy.com",
        "booking.com",
        "makemytrip.com",
        "tripadvisor.com",
        "apna.co",
        "naukri.com",
        "indeed.com",
        "glassdoor.com",
        "t.me",
    }
)
# Many tenants share one registrable domain on these builders, so the full host is the business's domain.
SHARED_HOSTS: frozenset[str] = frozenset(
    {
        "wixsite.com",
        "wix.com",
        "ueniweb.com",
        "icareheal.com",
        "weebly.com",
        "site123.me",
        "jimdosite.com",
        "mystrikingly.com",
        "strikingly.com",
        "webnode.page",
        "canva.site",
        "webs.com",
        "yolasite.com",
        "square.site",
        "000webhostapp.com",
        "web.app",
        "firebaseapp.com",
        "herokuapp.com",
        "pages.dev",
        "blogspot.com",
        "blogspot.in",
        "blogspot.co.uk",
        "blogspot.ae",
        "blogspot.sg",
        "blogspot.com.au",
        "wordpress.com",
        "webflow.io",
        "myshopify.com",
        "business.site",
        "carrd.co",
        "notion.site",
        "sites.google.com",
        "godaddysites.com",
        "zohosites.in",
        "zohosites.com",
        "netlify.app",
        "vercel.app",
        "github.io",
    }
)
# Free site builders: a "custom website" scores higher than these (Step 11.3).
FREE_BUILDER_HOSTS: frozenset[str] = frozenset(
    {
        "wixsite.com",
        "wix.com",
        "ueniweb.com",
        "icareheal.com",
        "weebly.com",
        "site123.me",
        "jimdosite.com",
        "mystrikingly.com",
        "strikingly.com",
        "webnode.page",
        "canva.site",
        "webs.com",
        "yolasite.com",
        "square.site",
        "blogspot.in",
        "business.site",
        "godaddysites.com",
        "sites.google.com",
        "blogspot.com",
        "wordpress.com",
    }
)

_TLD = tldextract.TLDExtract(suffix_list_urls=())  # offline: the bundled public suffix list, no network


def _host_parts(url: str) -> tuple[str, str] | None:
    raw = url.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw.lstrip("/")
    ext = _TLD(raw)
    if not ext.domain or not ext.suffix:
        return None
    registrable = f"{ext.domain}.{ext.suffix}".lower()
    host = ".".join(p for p in (ext.subdomain, ext.domain, ext.suffix) if p).lower()
    return registrable, host.removeprefix("www.")


def is_ignored_host(url: str | None) -> bool:
    """True when the URL belongs to a directory, social network or portal (not the business's own site)."""
    parts = _host_parts(url or "")
    if parts is None:
        return False
    registrable, host = parts
    if host == "sites.google.com":
        return False  # a site builder, handled in web_domain
    return registrable in IGNORED_HOSTS or any(host == h or host.endswith("." + h) for h in IGNORED_HOSTS)


def _google_site(url: str) -> str | None:
    """`sites.google.com/view/<name>` for a Google Sites URL (the tenant lives in the path)."""
    path = [p for p in urlsplit(url if "://" in url else "http://" + url).path.split("/") if p]
    if len(path) >= 2 and path[0] == "view":
        return f"sites.google.com/view/{path[1].lower()}"
    return f"sites.google.com/{path[0].lower()}" if path else None


def web_domain(url: str | None) -> str | None:
    """Registrable domain of a business website (`example.co.in`), the full host on shared builders
    (`drx.wixsite.com`), and None for directories and social networks."""
    parts = _host_parts(url or "")
    if parts is None:
        return None
    registrable, host = parts
    if host == "sites.google.com":
        return _google_site(url or "")
    if is_ignored_host(url):
        return None
    if registrable in SHARED_HOSTS:
        return host if host != registrable else None
    return registrable


def homepage(url: str | None) -> str | None:
    """`https://<host>/` for a business website, None for directories and social networks."""
    domain = web_domain(url)
    if domain is None:
        return None
    if "/" in domain:  # Google Sites: the tenant is part of the path
        return f"https://{domain}/"
    parts = _host_parts(url or "")
    assert parts is not None
    return f"https://{parts[1]}/"


def is_free_builder(domain: str | None) -> bool:
    """True when the web domain sits on a free site builder (`drx.wixsite.com`, `x.business.site`)."""
    if not domain:
        return False
    return any(domain == h or domain.endswith("." + h) or domain.startswith(h + "/") for h in FREE_BUILDER_HOSTS)


# ---------------------------------------------------------------------------------------------------
# URLs (7.4.3)
# ---------------------------------------------------------------------------------------------------

_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "_ga", "ref", "igshid")


def canonical_url(url: str) -> str:
    """Stable form of a URL for storage and dedupe: lower-case scheme and host, no `www.`, no fragment,
    no tracking parameters, no trailing slash (except the root)."""
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith(_TRACKING_PARAMS)
    ]
    path = re.sub(r"/+$", "", parts.path) or "/"
    netloc = parts.netloc.lower().removeprefix("www.")
    if netloc.endswith(":80") and parts.scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and parts.scheme == "https":
        netloc = netloc[:-4]
    return urlunsplit(((parts.scheme or "https").lower(), netloc, path, urlencode(query), ""))


# ---------------------------------------------------------------------------------------------------
# Phones (6.5.3, 10.3.2)
# ---------------------------------------------------------------------------------------------------

# An India STD code in brackets or with a leading 0 and a separator marks a landline (old engine `phone_kind`).
_STD_LANDLINE = re.compile(r"^\s*(?:\+91[\s-]*)?\(0?\d{2,4}\)[\s-]*\d|^\s*0\d{2,4}[\s-]+\d{6,8}\s*$")
PHONE_RUN = re.compile(r"(?<![\w+])(?:\+?\d[\d\s().-]{7,18}\d)(?!\w)")


def phone(raw: str | None, region: str) -> tuple[str, PhoneKind] | None:
    """E.164 number and its kind, or None when the text is not a valid number for `region` (`IN`, `AE`, ...)."""
    if not raw or not raw.strip():
        return None
    try:
        num = phonenumbers.parse(raw, region.upper())
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    pnt = phonenumbers.PhoneNumberType
    kind_code = phonenumbers.number_type(num)
    national = str(num.national_number)
    is_india = num.country_code == 91
    kind: PhoneKind
    if is_india and _STD_LANDLINE.search(raw):
        kind = "landline"
    elif kind_code == pnt.MOBILE:
        kind = "mobile"
    elif kind_code == pnt.FIXED_LINE:
        kind = "landline"
    elif kind_code in (pnt.TOLL_FREE, pnt.SHARED_COST):
        kind = "tollfree"
    elif kind_code == pnt.FIXED_LINE_OR_MOBILE:
        if is_india:
            kind = "mobile" if national[:1] in "6789" else "landline"
        elif num.country_code == 971:
            kind = "mobile" if national.startswith("5") else "landline"
        else:
            kind = "unknown"
    else:
        kind = "unknown"
    return e164, kind


def phones_in_text(text: str, region: str) -> list[tuple[str, PhoneKind]]:
    """Every valid number in free text, in order of appearance, without duplicates."""
    out: dict[str, PhoneKind] = {}
    for match in PHONE_RUN.finditer(text or ""):
        parsed = phone(match.group(0), region)
        if parsed and parsed[0] not in out:
            out[parsed[0]] = parsed[1]
    return list(out.items())


# ---------------------------------------------------------------------------------------------------
# Emails (10.3.5)
# ---------------------------------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
_OBFUSCATED_AT = re.compile(r"\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*", re.I)
_OBFUSCATED_DOT = re.compile(r"\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*", re.I)


def decode_email(raw: str | None) -> str | None:
    """`name[at]clinic[dot]com` and similar written forms to `name@clinic.com`; None when not an email."""
    if not raw:
        return None
    text = _OBFUSCATED_DOT.sub(".", _OBFUSCATED_AT.sub("@", raw.strip()))
    match = EMAIL_RE.search(text)
    return match.group(0).lower().rstrip(".") if match else None


def emails_in_text(text: str) -> list[str]:
    """Every email address in free text (lower case), in order of appearance, without duplicates."""
    seen: dict[str, None] = {}
    for match in EMAIL_RE.finditer(text or ""):
        seen.setdefault(match.group(0).lower().rstrip("."), None)
    return list(seen)


# ---------------------------------------------------------------------------------------------------
# Cities, localities and distance (6.5.4)
# ---------------------------------------------------------------------------------------------------


def _city_field(city: Any, name: str) -> Any:
    return city.get(name) if isinstance(city, dict) else getattr(city, name, None)


def _aliases(city: Any) -> list[str]:
    return [str(_city_field(city, "name")), *(_city_field(city, "aliases") or [])]


def _word_re(phrase: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in re.split(r"[\s_-]+", phrase.strip().lower()) if w]
    return re.compile(r"(?<![a-z0-9])" + r"[\s_-]+".join(words) + r"(?![a-z0-9])")


def city_for_text(text: str | None, cities: Sequence[Any]) -> str | None:
    """The city named in free text or a URL slug. The longest matching alias wins, so `Navi Mumbai` is not
    read as `Mumbai`, and `delhi-ncr` is read as Delhi. Word boundaries stop `Pune` matching `Punerwadi`."""
    low = (text or "").lower()
    if not low:
        return None
    best: tuple[int, str] | None = None
    for city in cities:
        for alias in _aliases(city):
            if alias and _word_re(alias).search(low):
                cand = (len(alias), str(_city_field(city, "name")))
                if best is None or cand[0] > best[0]:
                    best = cand
    return best[1] if best else None


def city_for(lat: float | None, lng: float | None, address: str | None, cities: Sequence[Any]) -> str | None:
    """The segment city for a point, or for an address when there is no point.

    City boxes overlap (Gurugram sits inside the Delhi box). When several boxes contain the point, a city named
    in the address wins; otherwise the smallest box, which is the most specific city.
    """
    if lat is None or lng is None:
        return city_for_text(address, cities)
    inside: list[tuple[float, Any]] = []
    for city in cities:
        min_lng, min_lat, max_lng, max_lat = _city_field(city, "bbox")
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            inside.append(((max_lng - min_lng) * (max_lat - min_lat), city))
    if not inside:
        return None
    if len(inside) > 1 and address:
        named = city_for_text(address, [c for _, c in inside])
        if named:
            return named
    return str(_city_field(min(inside, key=lambda t: t[0])[1], "name"))


def locality_for(address: str | None, localities: Iterable[str]) -> str | None:
    """The longest locality from the segment YAML that appears (as whole words) in the address."""
    low = (address or "").lower()
    best: str | None = None
    for loc in localities:
        if loc and _word_re(loc).search(low) and (best is None or len(loc) > len(best)):
            best = loc
    return best


def meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def clean_text(text: str | None, limit: int | None = None) -> str:
    """Collapse whitespace; optionally cut to `limit` characters on a word boundary."""
    s = _SPACES.sub(" ", unicodedata.normalize("NFKC", text or "")).strip()
    if limit is not None and len(s) > limit:
        cut = s[:limit]
        s = cut.rsplit(" ", 1)[0] if " " in cut[limit // 2 :] else cut
    return s
