# Sources and research

How the engine finds businesses and evidence (Steps 5 to 9 of `IMPLEMENTATION_PLAN.md`). The rules every source
follows are in [data-policy.md](data-policy.md); this page says what each source does, how fast, and what the
first live check measured.

- [Sources](#sources)
- [Stages](#stages)
- [Week 1 data check (12 Nov 2026)](#week-1-data-check-12-nov-2026)
- [Checked at build](#checked-at-build)
- [Sources deliberately not built](#sources-deliberately-not-built)

## Sources

All network access goes through `engine/src/nument_engine/http.py` (`PoliteClient`). Every source has a kill
switch in `settings.sources_enabled` and a row in `source_health`.

| Source | Module | Policy and pace | Gives | Runs | Status |
|---|---|---|---|---|---|
| Overture Maps | `sources/overture.py` | Open data. STAC catalog for the release, DuckDB on the GeoParquet files that cover each city box | Businesses with category, website, phone hint, point | Monthly | Live |
| Google Places (New) | `sources/places.py` | Official API, 5 requests a second, daily caps and free monthly allowances through the budget guard | IDs (free), listing details, review pain flags | Daily | Needs `GOOGLE_MAPS_API_KEY`; skips with a clear message until then |
| ART registry | `sources/art_registry.py` | Open data, 3 seconds per request, one page | Registered IVF clinics with email | Monthly | Live |
| OpenStreetMap | `sources/osm.py` | Overpass API, 10 seconds per request, tiles of at most 0.25 degrees | Gap filling, low trust | Monthly | Live |
| Apna jobs | `sources/apna.py` | Grey: 6 seconds per request, robots.txt obeyed, at most 300 pages a day, stops on a block | `hiring_frontdesk`, `hiring_builder` | Daily | Live |
| Careers pages | `sources/careers_watch.py` | Public pages, 2 seconds per host, one page per host a night | New roles and branches on known sites | Daily | Live |
| GDELT | `sources/gdelt.py` | Official API, one query every 6 seconds; a 429 waits once, then ends GDELT for the run | `news`, `new_branch`, `funding` | Daily | Live |
| Grounded search | `sources/grounded_search.py` | Through the AI router (Gemini with Google Search), inside the grounding quota | `public_ask` | Daily | Live with a Gemini key |
| Practo | `sources/practo.py` | Public pages, 5 seconds per request | A clinic's profile page for extraction | Research | Off until the founder approves |
| Adzuna | `sources/adzuna.py` | Official API | Job posts | Daily | Off; needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` and a coverage check |

When a source is blocked (401, 403, 429, 503 or a bot-check page) it rests 24 hours, then 72 hours, then
7 days for repeated blocks in 30 days. A grey source blocked twice in 7 days is switched off until the founder
turns it back on. A business website that blocks us is only skipped for the rest of the run. API quota errors
pause the API until midnight IST.

## Stages

| Stage | Module | What it does |
|---|---|---|
| Universe | `pipeline/universe.py` | Daily: clears Google listing data older than 30 days, free ID searches over a 14-day locality rotation, a targeted lookup of businesses that a signal created, Details inside the caps. Monthly: Overture, registries, OSM, `new_place` signals for places absent from the previous release, the dormant sweep |
| Resolve | `pipeline/resolve.py` | One real company is one row: same record, same Google or Overture id, same web domain (more than 300 m away is a branch), same published phone (never a shared or toll-free number), then name plus distance |
| Signals | `pipeline/signals.py` | Runs the watchers, links each signal to a business (creating it from the hint when needed), applies points and freshness windows, upserts on a stable dedupe key. Review pain never stores review text |
| Pre-filter | `pipeline/prefilter.py` | Rules R1 to R11, the queue priority, segment shares from `segments.daily_quota`, at most 10% fit-only, and the money check against today's spend |
| Research | `pipeline/research.py` | Crawls each queued business's own site (homepage plus up to 7 chosen pages), stores the visible text, and writes code facts from the business's own pages only. `extra.force_browser` (set by verification) makes the crawl use the browser |
| Extract | `pipeline/extract.py` | Builds each business's input (16,000 tokens at most), submits one `extract_facts` batch at night and turns the morning's results into quoted facts |

Code facts written by research, all stored as verified because code read them from the page:

| Field | Model | Value |
|---|---|---|
| `tel_link` | `code` | `{number, e164, kind, via: tel or whatsapp, label}`; quote is the raw link |
| `jsonld_phone` | `code` | `{phone, e164, kind}` from JSON-LD `telephone` |
| `mailto_link`, `jsonld_email` | `code` | `{email}` |
| `jsonld_name`, `jsonld_price_range`, `jsonld_employees`, `jsonld_job` | `rule` | From JSON-LD and microdata |
| `careers_url`, `locations_url`, `contact_form_url` | `rule` | `{url}` |
| `tech_stack` | `rule` | `{tools: [{tool, kind, page_url}], has_booking, has_whatsapp, has_chat, pays_for_software, runs_ads_tag, free_builder}` |
| `site_speed_mobile` | `rule` | The PageSpeed mobile score (morning, businesses graded B or better) |

## Week 1 data check (12 Nov 2026)

A small live run on a throwaway local database (no AI calls, nothing written to Supabase).

**Overture, release 2026-10-21.0, Baner and Aundh in Pune** (box 73.76, 18.54, 73.82, 18.58; one GeoParquet file
read; 17 seconds including the catalog lookups):

| Measure | Value |
|---|---|
| Clinic places in the box | 140 |
| With a website | 114 (81%) |
| With a phone (a hint only) | 138 (99%) |
| By category | dental 88, dermatology 19, physical therapy 14, counseling 9, psychology 5, fertility 3, hair loss 1, mental health clinic 1 |
| After resolution | 127 businesses: 10 places were other branches of a business with the same website, 3 matched an existing row |

**ART registry**: 4,767 rows on the page (the same count as the 12 Nov manual check), 704 in the clinics-in cities
(Bengaluru 167, Pune 136, Hyderabad 121, Delhi 112, Mumbai 90, Thane and Navi Mumbai 49, Gurugram 29, Noida 0),
every one with an email. 4 seconds.

**Three real clinic websites** found by Overture in that box, crawled at 2 seconds per request (23 requests in
all, robots.txt obeyed, no browser needed): 4, 6 and 4 pages read; 1, 3 and 2 phone links found (one a WhatsApp
link); JSON-LD phones on two sites; WordPress on all three, Google Analytics or Tag Manager on all three, no
booking, chat or WhatsApp vendor tool on any. One live finding changed the code: a treatment page called
"single visit crowns" was taken for a booking page, so the booking group now needs "visit us", not "visit".

## Checked at build

| Item | Finding |
|---|---|
| Overture release | Read from `https://stac.overturemaps.org/catalog.json` (`latest`); never hard-coded |
| Overture schema | v2.0.0: `taxonomy.primary`, `taxonomy.hierarchy`, `bbox` struct; `categories` no longer exists. The query selects the whole `bbox` struct because projecting `bbox.xmin` with `ORDER BY ... LIMIT` trips an internal error in DuckDB 2.0 |
| Overture taxonomy | Every segment code checked against `taxonomy.csv` of the release; five education and real estate codes did not exist and were replaced |
| ART registry | Public page, no CAPTCHA, robots.txt absent (everything allowed), 7 columns, emails written with `[at]` and `[dot]` |
| Apna | robots.txt allows job pages; `api/sitemap-index.xml` lists `job-listing-sitemap.xml`, which lists `active-job-listings-N.xml` (about 10,000 URLs each). City slugs include `pune-region`, `navi-mumbai`, `delhi-ncr`, `gurgaon-gurugram`. Job pages carry `JobPosting` JSON-LD |
| GDELT | Answers faster callers with HTTP 429 and a plain-text notice, even after a 5 second gap; the adapter waits 12 seconds once |
| Overpass | robots.txt disallows `/api/` to keep crawlers from indexing query URLs; the API itself has a public usage policy, which the adapter follows (few requests, 10 seconds apart, small tiles) |
| Places, PageSpeed | Not checked live: `GOOGLE_MAPS_API_KEY` is not set yet. Both skip cleanly and say so |
| Adzuna | India and UAE coverage not checked yet; the adapter is off |

## Sources deliberately not built

| Source | Why not |
|---|---|
| LinkedIn, X, Instagram pages | Founder rule (A.4.2), aggressive blocking and legal risk. LinkedIn and X appear only as search snippets |
| Facebook groups, WhatsApp and Telegram groups | Need login or membership; collecting members' numbers breaks DPDP and spam rules |
| Meta Ad Library, Google Ads Transparency | robots.txt disallows bots; no API for Indian commercial ads. Ads are checked by hand and recorded as `ads_running` in the app |
| Google Maps scraping | Breaks Maps terms; the Balanced tier uses the official API |
| Google review scrapers | Breaks Maps terms |
| JobSpy, Naukri, Indeed internal APIs | Private APIs and fake app identities (A.4.2); their posts can appear through grounded search snippets |
| Justdial, IndiaMART, Sulekha | Terms ban scraping, numbers are masked or sold |
| Internshala | Blocks AI crawlers; very few relevant clinic front-desk jobs |
| ABDM Health Facility Registry | CAPTCHA on public search, no bulk list |
| Google News RSS | robots.txt blocks `/rss` |
| Reddit | robots.txt blocks all bots; the API needs approval |
| Paid data brokers (Apollo, Lusha and similar) | Founder rule: no paid lists, phones must be self-published |
