# Decisions

Changes to the plan made while building and running the system, newest first. Each entry says what changed,
why, and how to undo it. The plan itself is [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).

## 2026-11-13 (evening): a near-100 plan, seven countries, 50 to 60 leads a day

The founder rated the engine on conversion (100 = nearly every lead converts) and wants paying clients who stay
on a retainer, any industry, any region; he is flexible on the tech. Rated about 40/100 that evening: data
accuracy about 80, can-pay about 65, need-now about 20 (33 of about 26,000 businesses had a fresh buying sign).

Founder's choices: English-speaking, high-pay countries (India, UAE, US, UK, Australia, Canada, Singapore);
marketing and design agencies as white-label partners; no hard floor abroad, about $750 at least; **50 to 60 A
and B leads a day**, so research goes to 800 a day, grounded searches to 400 and the AI cap to Rs 1,250.

- **Stated need from anywhere.** `job_feeds` reads the monthly Hacker News "Who is hiring?" thread (Algolia API),
  Himalayas contractor roles and We Work Remotely RSS; a cheap classify call says what kind of company it is and
  its home country, and only product companies and small businesses become firms leads. RemoteOK (terms ask a
  public link back) and Remotive (robots.txt) are not used. Live check: 15 posts, 5 real hiring leads, Rs 0.9.
- **Need-first segments abroad:** firms-ae, -us, -gb, -au, -ca, -sg (signals only). Remote companies without a
  city link by name; the website lookup stage finds their site.
- **Partner track:** partners-in, -us, -gb, -au, -ae (domain `partners`, migration 0015): marketing, advertising,
  social, branding and design agencies from Overture plus agencies posting developer roles. Being an agency is the
  point there; software, app and IT shops, staffing and recruitment firms stay competitors everywhere.
- **Volume abroad:** clinics-us, -gb, -au and professional-us, -gb, -au (law and accounting firms) from Overture.
  Category names were checked on release 2026-10-21.0 in Pune, London and Austin.
- **Email first** in the US, UK, Australia, Canada and Singapore (plan 18.4): reach counts a published decision
  maker's email as 1.0 and a company email as 0.7; every email draft there ends with Team Nument, the postal
  address (setting `outreach.postal_address`) and a one-line opt-out. WhatsApp stays first in India and the UAE.
- **Speed:** a 13:00 IST midday run (migration 0017) reads the day's new signals, scores and writes messages, and
  emails the A and B leads made since the morning email.
- **People:** the founder or owner of A and B leads from Google Search (plan 5.11.4), kept only when a backed
  sentence names them in charge of this business; name only, never a phone or email.
- **Found pain:** an old or phone-unfriendly website (no viewport, no HTTPS, copyright 5+ years old, jQuery 1
  or 2, old WordPress) is a slow_site signal; the careers watch finds pages by id (it matched 11 of 48 by URL).
- **Retainer fit:** +3 can-pay for a partner agency, a full-time builder hire or an online store; -4 at 200+ staff.
- **Learning:** one-tap Replied, a required lost reason, monthly retainer value and currency (migration 0016);
  the weekly report adds cuts by source, lost reasons and new retainers.
- **Fix:** a NUL character in one page failed the whole morning batch of 60; facts are cleaned and one bad
  business is skipped. The batch was collected again the same evening.

## 2026-11-13: lead quality toward 95 (founder: "not more than 50/100")

The first live morning gave 4 leads shown as "A, 56/100" and "B, 40/100". Live data showed 29 buying signals
across about 27,000 businesses, every researched business fit-only, and a formula that capped a business
without a signal at 50.

### Score s2.0: the number is the quality and the grade follows it

- **Change:** total = need (0 to 35) + can pay (0 to 35) + fit (0 to 10) + reach (0 to 20).
  - Need: signal points × category multiplier (stated need 3.5, visible pain 2.2, growth 2). Without a stated
    need it is capped at 24 (visible pain) or 12 (growth).
  - Can pay: the proxy points (capped at 30) scaled to 35.
  - Grades: A 75+, B 55 to 74, C 40 to 54, D under 40. Nobody reachable is D.
  - The judge moves the number, not the grade: +5 only with confidence 0.7 and two cited facts or signals,
    −8 for one grade lower, −15 for two. A named disqualifier (agency, chain, hospital, in-house tech) takes
    the lead below 40. The rule total stays in `reasons.rule_total`.
  - Fit-only leads per segment per day: up to 50% of the other new leads, at least 5.
- **Why:** a strong clinic without a signal scored 40 and the judge's lift showed "B, 40/100". Under s2.0 it
  scores about 55 to 63 (B), fresh visible pain about 75 to 87, and a stated need with money and a direct
  mobile 90 to 100. The founder approved strong fit-only clinics reaching B.
- **Undo:** `config/scoring.yaml` back to s1.0 and `SCORE_VERSION`. Stored rows keep their version.

### Pain that research finds becomes signals

- **Change:**
  - Roles on a business's own careers page (`careers_role` facts) become `hiring_frontdesk` or
    `hiring_builder`.
  - An ads tag on its pages becomes `ads_running`.
  - A new signal wakes a dormant business.
- **Why:** these were stored as facts and never scored, and a D business never came back.

### The website must belong to the listing

- **Change:** verify compares the listing's name with the site's own `business_name`, using distinctive
  words only.
  - When the site is in the listing's city, the business takes the site's name and keeps
    `extra.listing_name`.
  - Otherwise it is rejected as `wrong_website`.
- **Why:** the Overture listing "Ipromise English Speaking" carried bmconsultantsindia.com, so the message
  greeted "BM English Speaking".

### Education is high-ticket only (founder)

- **Change:**
  - Tutoring, language and computer classes are out of the categories.
  - Names with spoken English, tuition, abacus, play school and the like are rejected (`fit.exclude_names`).
  - Size is 150+ reviews or 3+ branches.

### The intent hunt rides on the review lookup

- **Change:** the grounded review lookup also reports, from the last 60 days:
  - a front-desk job post by the business;
  - review complaints about calls, replies or booking;
  - a new branch.

  An item becomes a signal only when a sentence the search results back contains the answer line. Snippet
  signals count less (hiring 6, review pain 5, new branch 4), and job boards are never fetched. Four lookups
  run at once.
- **Cost:** no extra calls. `grounded_search.per_day` is set to 250 at rollout, about ₹100 a day above the free
  tier.

### Need-first track: segment `firms-in` (founder)

- **Change:** Indian SMEs and startups of any industry that post a builder job or ask in public for a
  developer, agency or tech partner.
  - `universe: signals_only`: no map; every business comes from a stated need.
  - Grounded queries starting with "hiring:" make `hiring_builder` signals; the rest make `public_ask`. All
    run daily.
  - Agencies, IT services and staffing firms are excluded. A poster whose own industry has an enabled
    segment is routed there.
  - Job boards (Naukri, Indeed, Instahyre, Cutshort and others) are search snippets only, added to the
    never-fetch hosts. Freelance marketplaces are never used.
  - A new night stage `lookup` finds the official website of a signal-born business with one grounded
    search. The domain must be cited and the home page must name the business. Prefilter R10 no longer waits
    forever.
- **Why:** leads of 90+ need a stated need, which is how the old engine's best leads were found (D-038,
  D-042).
- **Undo:** switch `firms-in` off in Settings, or set `enabled: false` in its YAML.

### Sources

- **GDELT:** reads 3 days of news and retries a timeout once.
- **Apna:** fails from GitHub's network ("robots.txt unreachable"), though it works from a home connection.
  The rules forbid working around a block, so it stays as it is and its health check reports it.
- **Real estate:** its YAML now says `enabled: false`, matching the database.

## 2026-11-13: the morning email always goes out

- **Change:** the `reviews` stage stops after `reviews.minutes_per_run` (default 8) minutes and always leaves
  10 minutes of the run for score, judge, message and email; the businesses it did not reach wait for the
  next morning. The email phase runs even past the run's deadline. The morning job may take 45 minutes
  (deadline 40), up from 30 (26).
- **Why:** on 13 Nov 25 grounded review lookups took 16 minutes (about 38 seconds each), the run hit its
  deadline and skipped both the messages and the email. The repository is public, so Actions minutes are free.
- **Undo:** `RESERVE_S` and `reviews.minutes_per_run` in `pipeline/reviews.py`, `after_deadline` on the email
  phase in `pipeline/runs.py`, and `DEADLINE_MIN["morning"]` with the `morning.yml` timeout.

## 2026-11-13: runs start from Supabase, not from GitHub's scheduler

- **Change:** migration 0013 adds pg_cron and pg_net jobs in Supabase. Every 10 minutes they ping the web
  app's `/api/health`. At the planned IST times (night 02:00, morning 06:00, weekly Monday 07:00, monthly 1st
  22:30, backup Sunday 23:00) they start each GitHub workflow through `workflow_dispatch`. The GitHub token
  is fine-grained, Actions read and write on this repository only, and expires 13 Nov 2027. It is kept in
  Supabase Vault as `github_dispatch_token` and in Render as `GH_DISPATCH_TOKEN` (the Engine page Run
  buttons). The repository variable `SCHEDULES_ENABLED` is now `false`, so GitHub's own schedules do
  nothing and runs never double up; manual and database-dispatched runs always run.
- **Why:** on the first night GitHub started the 02:00 run at 06:46 IST, dropped the 06:00 morning run and
  pinged the web app only twice in eight hours, so no morning email went out and the app went to sleep.
  pg_cron fires on the minute.
- **Check:** `select * from cron.job_run_details order by start_time desc limit 10;` and
  `select id, status_code, created from net._http_response order by id desc limit 10;` (204 means GitHub
  accepted the dispatch). A missing token only logs a notice.
- **Renew:** before 13 Nov 2027, make a new token with the same permission and run
  `select vault.update_secret(id, '<token>') from vault.secrets where name = 'github_dispatch_token';`,
  then update `GH_DISPATCH_TOKEN` on Render.
- **Undo:** `select cron.unschedule(jobname) from cron.job where jobname like 'nlead-%';` and set
  `SCHEDULES_ENABLED` back to `true`.

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

### Email goes to an admin-managed list, one email per person

- **Change:** the engine emails the morning list (last phase of the morning run, non-essential, once per IST
  day), alerts (a failed run, spend past the alert line or at the cap, and the other alert-level health
  checks, once a day for each problem) and the weekly report, as HTML with a plain-text part, through Resend
  from `Nument Leads <leads@nument.in>` with replies to the founder. Recipients are the `notify_recipients`
  table (migration 0011), managed by admins on Settings > Email recipients, each with Morning list, Alerts,
  Weekly report and Active switches. While the table is empty, or cannot be read, `ALERT_EMAIL` gets
  everything. Each recipient gets a separate API call, so nobody sees another address. `nlead notify test
  --to <email>` sends a sample; `nlead notify preview --out <dir>` writes every email to files.
- **Why:** the founder wants the team to get the list by email, and alerts must reach more than one person.
  Money (spend, the cap, money won, the cost section) goes only to recipients who are admins in the app, or
  to the `ALERT_EMAIL` fallback; everyone else gets the same email without it (callers never see money).
- **Undo:** remove the `email` phase from `runs.morning_phases`; empty `RESEND_API_KEY` stops every email.
