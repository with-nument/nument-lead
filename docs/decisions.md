# Decisions

Changes to the plan made while building and running the system, newest first. Each entry says what changed,
why, and how to undo it. The plan itself is [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).

## 2026-11-12: review numbers and review pain without a Places key

### Practo is on, and code reads the profile, not only the AI

- **Change:** migration 0010 switches Practo on (`sources_enabled.practo`, `source_health.enabled`). The clinic
  profile index comes from `profiles-sitemap.xml` (robots.txt lists it), not from sitemaps with "clinic" in the
  name, which do not exist. A profile counts only when its page confirms it: the same website, or Practo's name
  holding every word of the business name plus a point within 1 km or Practo's locality in the address; a
  different website rejects it. Code writes `practo_reviews`, `staff_or_doctors`, `practo_fees` and
  `practo_claimed` facts from the page data, and recent stories feed `review_pain`. Practo waits outside the
  crawl slots, so its 5 second pace does not slow other sites, and it stops at the run's deadline.
- **Why:** the founder approved Practo. Without Places data clinics rarely reached grade A or B. The old
  matcher needed a locality in the slug, but most of our clinics carry the city as their locality. The claim is
  in the page data, not in the visible text, so the AI extraction alone never saw it.
- **Undo:** set `sources_enabled.practo` to false.

### Google Maps reviews with our own honest browser, not the gosom binary

- **Change:** new grey source `maps_reviews` (night phase after the batch submission, `nlead maps-reviews`):
  the research Chromium with our User-Agent reads one known business's listing, confirms it, and stores its
  rating and review count like Places numbers (30 days, never over Places data) plus `review_pain` from the
  reviews Maps shows first. One lookup at a time, 6 seconds apart, robots.txt checked, at most
  `maps_reviews.lookups_per_day` (100) and `maps_reviews.minutes_per_run` (4) a night. Any consent wall, CAPTCHA,
  "unusual traffic" page or sign-in prompt is a block: the source rests 24 hours, 72 hours, then 7 days, and a
  second block in 7 days switches it off.
- **Why:** the founder approved a low-rate public scraper. gosom/google-maps-scraper was the suggestion, but its
  release binary hard-codes a fake Windows Chrome 91 User-Agent, a Chromium flag that hides automation and a
  click through the consent form, and no flag turns them off; its fast mode impersonates a browser's TLS
  fingerprint. Patching and building it would add a Go build and a second Chromium to every night run. Our own
  reader needs no download at all. Sorting reviews by newest asks for a sign-in, so it is not done. The live
  check matched all three test clinics by website.
- **Cost:** about 14 seconds a lookup, so 4 minutes is about 15 to 20 lookups. The night estimate in the
  Actions budget goes from 27 to 31 minutes (about 1,950 of 2,000 free minutes a month). Raise
  `maps_reviews.minutes_per_run` only with minutes to spare.
- **Undo:** set `sources_enabled.maps_reviews` to false.

### Review pain from public reviews keeps one quoted sentence

- **Change:** new AI task `classify_reviews` (Flash-Lite, no thinking, about ₹0.03 a business) reads the reviews
  of the last 90 days. The `review_pain` signal from Practo or Maps keeps one sentence of a complaining review
  (checked to be in it, otherwise dropped) and the profile or listing URL. Without an AI answer the Places review
  patterns decide.
- **Why:** `classify_signal` is built for job posts and has no review mode. Places API content may not be
  stored, so Places review pain keeps no text; Practo and Maps pages are public, and a quote makes the pitch
  concrete. Reviewer names are never kept.
- **Undo:** remove the `classify_reviews` task; the patterns still find the obvious complaints.

### The grounded review lookup runs last

- **Change:** the morning `reviews` stage skips a business whose Maps lookup was confirmed in the last 30 days,
  and asks only for Google numbers when research matched its Practo profile. It also clears grounded and Maps
  numbers older than 30 days every morning, not only on mornings with candidates.
- **Why:** both night sources read the numbers directly and cost no search quota. A Practo match alone gives no
  Google count, which the size rule and can-pay tiers need, so that lookup still runs.
- **Undo:** the `maps_reviews` condition in `reviews.CANDIDATES_SQL` and `practo_covered` in `pipeline/reviews.py`.

## 2026-11-12: first live run

### Clinics of unknown size are researched when they have their own website

- **Change:** pre-filter rule R9 lets a business through with its size unknown when it has no review data at
  all and has its own website (`businesses.web_domain`). Research reads its doctors and branches; the Step 11
  fit gate drops the small ones.
- **Why:** without a Google Maps key no clinic has a review count, so only registry clinics passed R9 and the
  research queue stayed almost empty. A business known to be small (reviews below the segment minimum) is
  still skipped.
- **Undo:** remove the `unknown_with_site` branch in `pipeline/prefilter.py`.

### Fit-only research share is a setting, set to 50% for now

- **Change:** `settings.prefilter.fit_only_share` (default 0.10 in code) caps the share of today's research
  slots that go to businesses without a buying signal. Set to 0.5 on 12 Nov.
- **Why:** signals are still sparse (no Places reviews yet), and research itself finds the visible pain
  (no online booking, no WhatsApp button, slow site) that most clinic pitches rest on. Research costs under
  ₹1 per business in batch mode, well inside the ₹750 daily cap, and the budget ladder still stops fit-only
  research first when spend runs high.
- **Undo:** set `prefilter.fit_only_share` back to 0.1 once Places reviews and job signals fill the queue.

### Public-ask search: three tries per model, Gemini 4 Argon as the first fallback

- **Change:** a grounded search answer that cites no search gets two nudges before the next model; the chain
  is Gemini 3.8 Flash, then Gemini 4 Argon, then Flash-Lite. The prompt gets country and domain words.
- **Why:** in the first live night run Gemini answered four times without searching (it describes searches it
  never ran). After the change, 3 of 3 live queries were grounded for ₹1.34.
- **Undo:** `SEARCH_ATTEMPTS` in `llm/router.py` and the `grounded_search` fallbacks in `config/tasks.yaml`.

### A limited monthly universe run never marks an Overture release done

- **Change:** `settings.overture_done` records per segment the release whose full pull finished. Runs with
  `--limit` do not write it, do not move the diff baseline and do not run the dormant sweep.
- **Why:** a 40-record test pull used to count as complete, so the next full monthly run would have skipped
  the segment and marked unseen businesses dormant.

### GitHub workflows use repository-level secrets and variables

- **Change:** no GitHub environments. Each workflow passes `SHEET_MASTER_ID` and `SHEET_CALLER_ID` to prod
  runs only and `SHEET_STAGING_ID` to dev runs only.
- **Why:** environments need a paid plan on a private repository owned by a personal account. The rule that a
  dev run never writes a live sheet still holds.
