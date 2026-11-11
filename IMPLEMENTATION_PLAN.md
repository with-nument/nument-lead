# Nument Leads: Implementation Plan

| Field | Value |
|---|---|
| Project | `nument-leads`: a standalone lead engine and web app for Nument |
| Version | 1.0 |
| Written | 12 Nov 2026 |
| Owner | Founder (Nument) |
| Status | Agreed plan, not built yet |
| Audience | Anyone building this system, step by step, with no prior context |

> **How to read this document.** It is a build manual. Follow the steps in order. Each step has a goal, what you need first, exact actions, the files and code to create, and a **Done when** checklist. Do not move to the next step until the current step's **Done when** list is fully ticked.

---

## Table of contents

- [Part A: Context, decisions and architecture](#part-a-context-decisions-and-architecture)
  - A.1 What we are building and why
  - A.2 Decisions already made (do not re-decide)
  - A.3 What is out of scope
  - A.4 Data and outreach rules
  - A.5 Glossary
  - A.6 System overview
  - A.7 Tech stack
  - A.8 Repository layout
  - A.9 Environments
  - A.10 Budget, quotas and limits
  - A.11 Conventions used in this document
- [Step 0: Accounts, access and machine setup](#step-0-accounts-access-and-machine-setup)
- [Step 1: Repository and project skeleton](#step-1-repository-and-project-skeleton)
- [Step 2: Database (Supabase Postgres)](#step-2-database-supabase-postgres)
- [Step 3: Segments configuration (domain x country)](#step-3-segments-configuration-domain-x-country)
- [Step 4: AI router (Gemini + OpenAI)](#step-4-ai-router-gemini--openai)
- [Step 5: Source adapters](#step-5-source-adapters)
- [Step 6: Universe builder and entity resolution](#step-6-universe-builder-and-entity-resolution)
- [Step 7: Signal watchers](#step-7-signal-watchers)
- [Step 8: Rule pre-filter and research queue](#step-8-rule-pre-filter-and-research-queue)
- [Step 9: Deep research](#step-9-deep-research)
- [Step 10: Verification](#step-10-verification)
- [Step 11: Scoring and grading](#step-11-scoring-and-grading)
- [Step 12: Message writing](#step-12-message-writing)
- [Step 13: Google Sheet two-way sync](#step-13-google-sheet-two-way-sync)
- [Step 14: Orchestration with GitHub Actions](#step-14-orchestration-with-github-actions)
- [Step 15: Web app](#step-15-web-app)
- [Step 16: Learning loop and reports](#step-16-learning-loop-and-reports)
- [Step 17: Quality: tests, golden set, evals, CI](#step-17-quality-tests-golden-set-evals-ci)
- [Step 18: Compliance, safety and security](#step-18-compliance-safety-and-security)
- [Step 19: Cost controls](#step-19-cost-controls)
- [Step 20: Migrating the old lead engine](#step-20-migrating-the-old-lead-engine)
- [Step 21: Go-live](#step-21-go-live)
- [Step 22: Operations runbook](#step-22-operations-runbook)
- [Step 23: Expansion playbook (new domain or country)](#step-23-expansion-playbook-new-domain-or-country)
- [Step 24: Timeline and milestones](#step-24-timeline-and-milestones)
- [Appendices](#appendices)

---

# Part A: Context, decisions and architecture

## A.1 What we are building and why

### A.1.1 The problem
Nument is an AI-first, full-stack software studio. It builds websites, apps, AI assistants and automation. The founder's main problem is **finding new, very high-quality clients who can pay ₹50K or more**. The old lead engine was run by hand in chat sessions, its free sources dried up, and on 12 Nov 2026 the sheet held only 13 leads, all graded B.

### A.1.2 The solution in one sentence
A **standalone system** that runs by itself every night, finds businesses across many domains and countries that have a real problem Nument can solve, proves that problem with evidence, checks they can pay, writes a personal first message, and puts the best leads into a **web app and a Google Sheet** by 7:30 am IST.

### A.1.3 What the founder does (not automated)
1. Opens the web app or the sheet.
2. Taps one button to open WhatsApp with the message already typed, then presses send.
3. Handles replies, calls, proposals, building and closing.
4. Marks the stage of each lead (Contacted, Talking, Won and so on). The engine learns from these stages.

### A.1.4 The business model this engine serves
| Step | What happens | Who |
|---|---|---|
| 1. Find | Businesses that stated a problem, or whose problem we can prove with evidence | Engine |
| 2. Pitch | A personal message about *their* problem and how we would solve it | Engine writes it, founder sends it |
| 3. Lock | Call, scope, proposal, deal | Founder |
| 4. Build | A solution made for their problem, assembled from Nument's reusable blocks | Founder's team |
| 5. Grow | Monthly fee to run and improve it, then bigger builds (automation, apps, websites) and referrals | Founder |

### A.1.5 Success measures
| Measure | Target |
|---|---|
| Businesses researched per day | Up to 300 |
| Good leads (grade A or B) per day | About 100 at full run |
| Leads with a phone the business published | 90% or more |
| Wrong contact rate | Under 5% |
| Age of the buying signal | Under 30 days |
| Reply rate per segment | 10% or more (judged after 100 contacts) |
| Daily spend on AI and APIs | Hard cap ₹750, alert at ₹600 |
| Fact accuracy on the golden set | 95% or more |
| Good leads in the top 50 of the golden set | 80% or more |

---

## A.2 Decisions already made (do not re-decide)

These were agreed with the founder between Oct and 12 Nov 2026. Treat them as requirements.

### A.2.1 Targets
- **Who:** owner-led businesses that spend money to get customers but lose them to slow replies and manual work, and that can pay ₹50K or more.
- **Domains:**
  1. Clinics (skin and hair, aesthetic, IVF and fertility, dental chains, physio and therapy groups)
  2. Real estate (developers, brokers, channel partners)
  3. Education (coaching institutes, study-abroad consultants, academies)
  4. D2C and e-commerce brands
  5. Hospitality and travel (hotels, travel agents)
  6. Auto dealers and service centres
  7. Insurance and loan distributors
  8. Gym, salon and spa chains
  9. Professional firms (law, consulting) and funded startups
- **Skip:** tiny solo shops, big corporates, hospital chains, franchise outlets controlled by a head office, agencies and software vendors (they are competitors).
- **Countries, in waves:**
  - Wave 1: India + UAE
  - Wave 2: Saudi Arabia, Qatar, UK, Singapore
  - Wave 3: US, Australia
- **Sales capacity is never a reason to limit volume.** The founder owns operations. The engine optimises only for the number of high-quality leads.

### A.2.2 Offer and pitch
- The **lead's signal decides the pitch**:
  - **Stated need** (job post for a builder, public ask, tender): pitch as an agency that will solve exactly that need.
  - **Visible pain** (review complaints, ad spend with slow replies, front-desk hiring): lead with the packaged outcome for the domain, "No lead goes cold": every enquiry answered within seconds, followed up until it books.
  - **Fit only** (no signal): a small test group to learn whether signals matter.
- On the call the founder acts as an agency and sells custom work built from reusable blocks.
- Price guide: setup ₹50K to ₹1.5L plus a monthly fee of ₹10K to ₹25K. Abroad, 3 to 5 times that.
- Packaged outcome names per domain:

| Domain | Packaged outcome name |
|---|---|
| Clinics | AI front desk |
| Real estate | AI lead qualifier and site-visit booking |
| Education | AI admissions counsellor |
| D2C | AI support, order and cash-on-delivery confirmations |
| Hospitality and travel | AI enquiry to quote |
| Auto | AI lead follow-up and service booking |
| Insurance and loans | AI renewals and document chasing |
| Gym, salon, spa | AI bookings and renewals |
| Firms and startups | Custom AI workflows (agency pitch) |

### A.2.3 Message voice (approved by the founder)
- Casual, human, like a person texting. Polished, structured copy reads like a bot and is rejected.
- Shape: "Hi Dhruv, saw Calmveda's post on Internshala about Claude agents for Amazon and Tally." Then one honest line ("We're Nument, a small dev team, and we build this kind of thing."), then one idea in plain words, then one short, varied question.
- 30 to 60 words. No links, emojis, dashes or prices in the first message. Never "reaching out", "businesses like yours", "AI-powered", "hope you're well".
- Sender is the associate, **Aditya** (WhatsApp shows his name, so the message does not introduce him).

### A.2.4 Engine and infrastructure
| Area | Decision |
|---|---|
| Runtime AI | Gemini + OpenAI only. Claude helps build it, and is not used at runtime |
| Provider fallback | Every AI task has a fallback chain, and **Gemini can run every task on its own**. OpenAI is unavailable as of 12 Nov 2026, so it starts disabled (`providers_enabled.openai = false`). If any provider fails, the router switches automatically and the pipeline never stops |
| Quality tier | Balanced tier (Tier 2 in the plan PDF) |
| Volume | Up to 300 businesses researched per day, about 100 good leads |
| Spend cap | ₹750 per day hard cap, alert at 80% (₹600) |
| Scheduler | GitHub Actions: two short nightly runs (02:00 and 06:00 IST) plus sheet syncs |
| Database | Supabase Postgres (free tier), source of truth |
| Views | Web app **and** Google Sheet, both editable, kept in sync |
| Web app | Next.js, hosted on **Render** |
| Login | **Email + password** (Supabase Auth), invite only |
| Design | **Nument kit**: Newsreader, Figtree, DM Mono, brand indigo accents, calm and uncluttered |
| Code | One private GitHub repo for engine + web app. Built and tested **locally first**; nothing is pushed to GitHub until the founder says so. Commits are authored by the founder only, with no AI co-author lines |
| Local testing | Uses only the Gemini key with a small spend guard (`--max-spend-inr`, default ₹50 per test session) |

---

## A.3 What is out of scope

The founder handles these. Do not build them unless asked.
- Automatic sending of WhatsApp messages, emails or calls.
- Reading replies from WhatsApp, or reply notifications.
- Automatic follow-ups. The engine only **drafts** day 3 and day 7 follow-ups for the founder to send.
- Booking calls, proposals, invoicing and payments.
- A client-facing portal.

---

## A.4 Data and outreach rules

These rules are enforced in code (Step 18). They come from the founder's decisions of 12 Nov 2026.

### A.4.1 Allowed
- Public pages and official APIs.
- Grey-area scraping of public pages (where a site's terms ban robots) **at a slow rate**, with an honest User-Agent, stopping when blocked. The founder approved this on 12 Nov 2026.
- Search-engine results (for example Gemini grounded search) that mention LinkedIn or X posts. We read the search snippet, never the LinkedIn or X page.

### A.4.2 Never
- Logging in to any third-party site, or using fake accounts.
- Solving or bypassing CAPTCHAs.
- Proxies, IP rotation, residential proxy networks, or any block-evasion technique.
- Faking an app identity or calling private or undocumented APIs (for example JobSpy's Indeed mobile API).
- Fetching linkedin.com, x.com, twitter.com or instagram.com pages.
- Buying data from brokers, using leaked lists, Truecaller-style lookups, or guessing phone numbers.

### A.4.3 Phones and personal data
- Use a phone number only if the business published it itself: first choice is its own website, fallback is its own Google listing. The fallback is a proposed update to the old rule D-033; it must be marked "from Google listing".
- Store the minimum personal data: business contacts and the decision maker's name and role as published. Nothing from personal social profiles.
- Respect opt-outs forever (suppression list).
- India DPDP Act: personal data the person made public is exempt, but keep it minimal and purposeful.

### A.4.4 Google Places terms
- Store only the Google `place_id` permanently.
- Other Places content (rating, review count, phone, website) may be used for scoring but must be refreshed and never kept longer than 30 days. Store derived features (for example "busy: 100+ reviews") instead of raw content where possible.
- Never store review text. Store only the derived signal ("reviews mention unanswered calls") plus a link to the Google listing.

---

## A.5 Glossary

| Term | Meaning |
|---|---|
| Segment | One domain in one country, for example `clinics-in` (clinics in India) or `realestate-ae` (real estate in UAE). Each segment has its own config file. |
| Universe | Every business in a segment that could be a client, before any signal. Refreshed monthly. |
| Business | One real company, after duplicates from different sources are merged. |
| Source record | One raw record from one source (an Overture place, a Places result, a job post). Many source records map to one business. |
| Signal | A dated piece of evidence that a business needs help now (hiring a receptionist, review complaints, a public ask, a new branch). |
| Stated need | A signal where the business wrote down what it needs (job post for a builder, public ask, tender). |
| Visible pain | A signal where the need is shown by evidence (complaints about missed calls, hiring front-desk staff, heavy ads with no booking). |
| Can-pay proxies | Measurable signs a business can pay ₹50K+: branches, staff, reviews, price points, paid software already in use. |
| Reach | How we can contact the decision maker: own mobile, business mobile, landline, email, form. |
| Fact | One piece of information extracted from a page, always stored with the exact quote and the page URL. |
| Verified fact | A fact whose quote was found again in the stored page text by code (not by AI). |
| Score | The numeric result of fit, can-pay, intent and reach. |
| Grade | A, B, C or D, derived from the score. A and B go to the sheet and app. |
| Pitch mode | `stated_need`, `visible_pain` or `fit_only`. Decides how the message is written. |
| Test group | A label that lets us compare what works (segment, pitch mode, angle, fit-only control). |
| Lead | A graded business with a message, ready to send, with a stage. |
| Stage | Where a lead is in the sales process (New, Contacted, Talking, and so on). |
| Run | One execution of the nightly or morning pipeline, logged with stats and costs. |
| Golden set | 100 businesses labelled by the founder, used to test quality before any change goes live. |
| Kill switch | A setting that turns off one source or one segment instantly. |

---

## A.6 System overview

### A.6.1 The nine automated stages
```
            +------------------------- NIGHT RUN (02:00 IST) --------------------------+
            |                                                                          |
 sources -> |  1 UNIVERSE  ->  2 SIGNALS  ->  3 PRE-FILTER  ->  4 RESEARCH (crawl)      |
            |  (monthly)      (daily)        (rules only)      + submit AI batch       |
            +--------------------------------------------------------------------------+
                                              |
            +------------------------ MORNING RUN (06:00 IST) -------------------------+
            |                                                                          |
            |  collect AI batch -> 5 VERIFY -> 6 SCORE + JUDGE -> 7 WRITE MESSAGE       |
            |                   -> 8 PUSH TO SHEET (and app reads the DB directly)     |
            +--------------------------------------------------------------------------+
                                              |
            +-------------- DAYTIME (hourly) --------------+   +---- WEEKLY (Mon) ----+
            |  SHEET SYNC: pull sheet edits, push changes   |   |  9 LEARN + REPORT    |
            +-----------------------------------------------+   +----------------------+

  Founder: web app or sheet -> one tap opens WhatsApp -> sends -> marks stages -> engine learns
```

### A.6.2 Where data lives
```
 GitHub Actions (Python engine)  --service role-->  Supabase Postgres  <--user session (RLS)--  Web app (Render)
            |                                             ^
            |---- Google Sheets API (service account) ----|  (two-way sync, DB is the source of truth)
            |
            |---- Gemini API, OpenAI API (AI)
            |---- Google Places API, Overture (S3), registries, job boards, company websites, GDELT
```

### A.6.3 Key design principles
1. **The database is the single source of truth.** The app and the sheet are views that can edit; every edit lands in the database.
2. **Every fact has a quote and a URL, and code re-checks the quote.** AI can never put an unverified claim in front of the founder.
3. **Every step is idempotent.** Running it twice gives the same result. A crashed run can simply be re-run.
4. **Cheap before expensive.** Free rules filter first, small models next, the top model only on the best half.
5. **Config, not code, for new markets.** A new domain or country is a new YAML file plus, at most, one new source adapter.
6. **Fail safe.** If a source blocks us, we stop using it and record it. If spend hits the cap, non-essential work stops.
7. **Never break the founder's view.** The sheet is only rewritten after a full successful build (lesson from the 12 Nov 2026 crash).

---

## A.7 Tech stack

Pin exact versions in `uv.lock` and `pnpm-lock.yaml` on the day you build. Use the latest stable versions available then.

### A.7.1 Engine (Python)
| Purpose | Tool | Notes |
|---|---|---|
| Language | Python 3.12 | Best wheel support for duckdb, playwright, pyarrow |
| Package manager | uv | Fast, lockfile, manages the Python version |
| HTTP | httpx | Async, timeouts, HTTP/2 |
| Retries | tenacity | Exponential backoff |
| Data models | pydantic v2 + pydantic-settings | Validation, settings from env |
| Config files | PyYAML | Segment files |
| Database | psycopg 3 (binary) | Direct SQL to Supabase via the pooler |
| Overture data | duckdb + pyarrow | Query GeoParquet on S3 by bounding box |
| Browser | playwright (Chromium) | Only for JavaScript-heavy pages |
| Page text | trafilatura | Clean main text and links |
| Structured data | extruct | JSON-LD, microdata (LocalBusiness, JobPosting) |
| HTML parsing | selectolax | Fast link and table parsing |
| Phones | phonenumbers | Parse, E.164 format, mobile vs landline |
| Domains | tldextract | Registrable domain for dedupe |
| Fuzzy matching | rapidfuzz | Name matching, quote verification |
| AI | google-genai, openai | Official SDKs |
| Sheets | gspread + google-auth | Same service account as today |
| Prompt templates | jinja2 | Prompts as files |
| CLI | typer + rich | `nlead` command |
| Logging | structlog | JSON logs with run ids |
| Tests | pytest, pytest-asyncio, respx | respx mocks httpx |
| Lint and types | ruff, mypy | |

### A.7.2 Web app (TypeScript)
| Purpose | Tool | Notes |
|---|---|---|
| Framework | Next.js (latest stable, App Router) | Same family as nument.in |
| Runtime | Node 22 LTS or newer | Render supports it |
| Package manager | pnpm | |
| Auth and data | @supabase/ssr + @supabase/supabase-js | Email + password, cookies |
| Styling | Tailwind CSS + Nument kit tokens | `tokens.css` from the design kit |
| Fonts | next/font/google | Newsreader, Figtree, DM Mono |
| Tables | @tanstack/react-table | Leads list |
| Drag and drop | @dnd-kit/core | Pipeline board |
| Forms | react-hook-form + zod | Validation |
| Charts | recharts | Insights |
| Dates | date-fns + date-fns-tz | IST display |
| Icons | lucide-react | Small, consistent icon set |
| Tests | Playwright (end to end), vitest (units) | |

### A.7.3 Services
| Service | Plan | Used for |
|---|---|---|
| GitHub | Private repo, Actions free tier (2,000 minutes a month) | Code, scheduler, CI, secrets |
| Supabase | Free tier (2 projects: dev and prod) | Postgres, Auth, Storage |
| Render | Web service. Free tier sleeps after 15 minutes idle; Starter (about $7 a month) stays awake | Web app hosting |
| Google Cloud | Existing project `lead-engine-510307` | Places API (New), PageSpeed Insights API, Sheets service account |
| Google AI Studio | Gemini API key, paid tier | AI |
| OpenAI | API key, paid | AI |

---

## A.8 Repository layout

```
nument-leads/
├── IMPLEMENTATION_PLAN.md          # this file
├── README.md                       # short intro + how to run locally
├── .gitignore
├── .editorconfig
├── .env.example                    # every variable, no values
├── render.yaml                     # Render blueprint for the web app
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci.yml                  # lint, tests, eval subset on every push
│       ├── night.yml               # 02:00 IST pipeline part 1
│       ├── morning.yml             # 06:00 IST pipeline part 2
│       ├── sheet-sync.yml          # daytime two-way sheet sync
│       ├── weekly.yml              # Monday learning + report + audit
│       ├── monthly.yml             # universe refresh
│       └── backup.yml              # weekly encrypted database dump
├── supabase/
│   ├── config.toml
│   ├── migrations/
│   │   ├── 0001_core.sql
│   │   ├── 0002_views.sql
│   │   ├── 0003_rls.sql
│   │   └── 0004_seed.sql
│   └── tests/
│       └── rls_test.sql
├── engine/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── README.md
│   ├── config/
│   │   ├── prices.yaml             # model and API prices, FX rate
│   │   ├── tasks.yaml              # AI task -> model mapping per tier
│   │   └── exclusions.yaml         # big chains, hospitals, agencies to skip
│   ├── segments/
│   │   ├── clinics-in.yaml
│   │   ├── realestate-in.yaml
│   │   ├── education-in.yaml
│   │   ├── clinics-ae.yaml
│   │   ├── realestate-ae.yaml
│   │   └── education-ae.yaml
│   ├── prompts/
│   │   ├── classify_signal.md
│   │   ├── extract_facts.md
│   │   ├── verify_flagged.md
│   │   ├── judge_lead.md
│   │   ├── write_message.md
│   │   ├── check_message.md
│   │   ├── grounded_public_asks.md
│   │   └── weekly_audit.md
│   ├── src/nument_engine/
│   │   ├── __init__.py
│   │   ├── cli.py                  # `nlead` command (typer)
│   │   ├── settings.py             # env settings (pydantic-settings)
│   │   ├── logging.py              # structlog setup
│   │   ├── db.py                   # connection pool, helpers, upserts
│   │   ├── models.py               # pydantic models shared across steps
│   │   ├── segments.py             # load + validate segment YAML
│   │   ├── budget.py               # spend tracking + cap guard
│   │   ├── http.py                 # polite fetch, robots, rate limits, cache
│   │   ├── llm/
│   │   │   ├── router.py           # task -> provider/model, cost log
│   │   │   ├── gemini.py
│   │   │   ├── openai_provider.py
│   │   │   ├── batch.py            # submit/poll/ingest batch jobs
│   │   │   └── prompts.py          # load + render prompt files
│   │   ├── sources/
│   │   │   ├── base.py
│   │   │   ├── overture.py
│   │   │   ├── places.py
│   │   │   ├── art_registry.py
│   │   │   ├── practo.py
│   │   │   ├── apna.py
│   │   │   ├── careers_watch.py
│   │   │   ├── gdelt.py
│   │   │   ├── grounded_search.py
│   │   │   ├── osm.py
│   │   │   └── adzuna.py
│   │   ├── pipeline/
│   │   │   ├── universe.py
│   │   │   ├── resolve.py          # entity resolution / dedupe
│   │   │   ├── signals.py
│   │   │   ├── prefilter.py
│   │   │   ├── research.py         # crawl + build AI inputs
│   │   │   ├── extract.py          # AI fact extraction (batch)
│   │   │   ├── verify.py
│   │   │   ├── score.py
│   │   │   ├── judge.py
│   │   │   ├── message.py
│   │   │   └── runs.py             # night + morning orchestration
│   │   ├── research/
│   │   │   ├── pages.py            # choose pages to read
│   │   │   ├── text.py             # trafilatura wrapper
│   │   │   ├── structured.py       # extruct wrapper
│   │   │   ├── techstack.py        # widget/CMS detection
│   │   │   └── quality.py          # PageSpeed / Lighthouse score
│   │   ├── sheet/
│   │   │   ├── push.py             # DB -> sheet (Today, Pipeline, Lead details)
│   │   │   ├── pull.py             # sheet -> DB (two-way)
│   │   │   └── design.py           # colours, formats (ported from old sync_sheet.py)
│   │   ├── learn/
│   │   │   ├── metrics.py
│   │   │   ├── reweight.py
│   │   │   └── report.py
│   │   └── ops/
│   │       ├── health.py
│   │       ├── backup.py
│   │       └── migrate_legacy.py
│   ├── tests/
│   │   ├── fixtures/               # saved HTML, API responses
│   │   └── test_*.py
│   └── evals/
│       ├── golden/                 # labels exported from the app
│       └── run_eval.py
├── web/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── middleware.ts
│   ├── src/
│   │   ├── app/                    # routes (see Step 15)
│   │   ├── components/
│   │   ├── lib/                    # supabase clients, queries, utils
│   │   └── styles/                 # tokens.css, globals.css
│   └── tests/                      # Playwright end-to-end tests
└── docs/
    ├── runbook.md
    ├── data-policy.md
    └── segments-guide.md
```

---

## A.9 Environments

| Environment | Database | Sheet | Web app | Used for |
|---|---|---|---|---|
| Local | Supabase **dev** project | A **staging** copy of the sheet | `localhost:3000` | Building and testing |
| Dev | Supabase **dev** project | Staging sheet | Render preview (optional) | Dry runs, evals |
| Prod | Supabase **prod** project | The real `Leads-main` (master) and `Leads-Associate` (caller) sheets | Render production (`leads.nument.in`, optional) | Real use |

Rules:
- Never point a local run at prod unless you are doing the Step 21 cutover.
- Every command supports `--dry-run` (no writes to the sheet, no batch submission) and `--limit N`.

---

## A.10 Budget, quotas and limits

### A.10.1 Money
| Item | Daily | Monthly | Notes |
|---|---|---|---|
| AI (Gemini + OpenAI) | about ₹210 at 100 researched per day; about ₹650 at 300 per day | ₹6.3K to ₹20K | About ₹7 per researched business on the Balanced tier |
| Hard cap | ₹750 | | Alert at ₹600. At the cap, non-essential tasks stop |
| Google Places | ₹0 inside free caps | ₹0 | India: details 7K free per month per SKU; abroad about 1K free |
| GitHub Actions | ₹0 | ₹0 | Inside 2,000 minutes per month (Step 14.6) |
| Supabase | ₹0 | ₹0 | Free tier |
| Render web app | ₹0 (sleeps) or about ₹600 (Starter, always on) | | Founder's choice at go-live |

### A.10.2 Quotas and limits to respect
| Resource | Limit | Our setting |
|---|---|---|
| Businesses researched | | 300 per day max (`settings.research_per_day`) |
| Places Text Search (IDs only) | Free, unlimited | Throttle 5 requests per second |
| Places Details Enterprise (India) | 7K free per month | 230 per day cap in Cloud console |
| Places Details + reviews (India) | 7K free per month | 230 per day cap |
| Places Details abroad | About 1K free per month | 30 per day cap per SKU |
| Gemini grounded search | 5K queries free per month | 160 per day |
| GitHub Actions | 2,000 minutes per month (private repo) | Budget in Step 14.6 |
| Supabase free | 500 MB database, 1 GB storage, pauses after 7 days idle | Nightly jobs keep it active; prune raw pages |
| WhatsApp (founder sending) | New-chat limits on fresh numbers | Start at 30 new chats per day per number, grow slowly |

---

## A.11 Conventions used in this document

- `$ command` means run it in a terminal. Do not type the `$`.
- Paths are relative to the repository root `nument-leads/` unless they start with `~`.
- **Done when** lists are acceptance criteria. Every item must be true before moving on.
- **Check** boxes in Done when lists are written as `- [ ]`.
- "Verify at build" means the fact (a model name, a price, a field name) changes often and must be confirmed against the official source on the day you build.
- Times are IST (UTC+5:30) unless written as UTC. GitHub Actions cron uses UTC.
- Money: ₹ for INR, $ for USD. FX rate in `engine/config/prices.yaml` (default ₹88 per $).

---

## A.12 Shared names (the contract every step uses)

Every step below uses exactly these names. If you change one, change it everywhere.

### A.12.1 Database tables and key columns
Full SQL is in Step 2. Columns listed here are the ones other steps rely on.

| Table | Key columns |
|---|---|
| `settings` | `key` (pk), `value` (jsonb). Keys: `daily_cap_inr` (750), `alert_pct` (80), `research_per_day` (300), `fx_inr_per_usd` (88), `tier` ("balanced"), `sheet_sync_enabled` (true), `sources_enabled` (map of source to bool), `segments_enabled` (map of segment to bool), `providers_enabled` (map, `openai: false` until OpenAI is available again) |
| `segments` | `id` (pk, e.g. `clinics-in`), `domain`, `country`, `enabled`, `daily_quota`, `config` (jsonb copy of the YAML), `updated_at` |
| `businesses` | `id` (uuid), `segment_id`, `name`, `norm_name`, `website`, `web_domain`, `country`, `city`, `locality`, `address`, `lat`, `lng`, `category`, `subcategory`, `place_id`, `overture_id`, `branches_count`, `staff_count`, `review_count`, `rating`, `places_fetched_at`, `status` (`candidate`, `queued`, `researched`, `qualified`, `rejected`, `suppressed`, `dormant`), `reject_reason`, `first_seen_at`, `last_seen_at`, `researched_at`, `created_at`, `updated_at` |
| `source_records` | `id`, `source`, `source_key`, `business_id`, `payload` (jsonb), `fetched_at`. Unique (`source`, `source_key`) |
| `signals` | `id`, `business_id`, `type`, `category` (`stated_need`, `visible_pain`, `growth`, `money`), `points`, `observed_at`, `expires_at`, `source`, `url`, `quote`, `details` (jsonb), `dedupe_key` (unique), `created_at` |
| `pages` | `id`, `business_id`, `url` (unique), `fetched_at`, `http_status`, `render_mode` (`http`, `browser`), `title`, `text`, `text_hash`, `robots_allowed` |
| `facts` | `id`, `business_id`, `field`, `value` (jsonb), `quote`, `url`, `page_id`, `model`, `verified` (bool), `verify_score`, `verified_at`, `created_at` |
| `contacts` | `id`, `business_id`, `name`, `role`, `phone_e164`, `phone_type` (`mobile`, `landline`, `tollfree`, `unknown`), `email`, `source` (`website`, `google_listing`, `registry`, `other`), `source_url`, `quote`, `is_decision_maker`, `verified`, `do_not_contact` |
| `scores` | `id`, `business_id`, `version`, `fit`, `can_pay`, `intent`, `reach`, `total` (0 to 100), `grade` (`A`, `B`, `C`, `D`), `pitch_mode`, `reasons` (jsonb), `judge_grade`, `judge_note`, `judge_model`, `computed_at` |
| `leads` | `id`, `business_id`, `segment_id`, `score_id`, `grade`, `pitch_mode`, `test_group`, `angle`, `message`, `message_alt`, `followup_d3`, `followup_d7`, `message_model`, `message_check_score`, `stage`, `owner_id`, `wa_at`, `call_at`, `d3_at`, `d7_at`, `meeting_at`, `next_step`, `due_at`, `deal_value_inr`, `notes`, `created_at`, `updated_at`, `last_activity_at` |
| `activities` | `id`, `lead_id`, `user_id`, `source` (`app`, `sheet`, `engine`), `type`, `at`, `payload` (jsonb) |
| `feedback` | `id`, `lead_id`, `user_id`, `rating` (-1 or 1), `reason`, `at` |
| `suppression` | `id`, `phone_e164`, `email`, `web_domain`, `reason`, `added_by`, `added_at` |
| `runs` | `id`, `kind` (`night`, `morning`, `sheet_sync`, `weekly`, `monthly`, `manual`), `started_at`, `finished_at`, `status` (`running`, `ok`, `partial`, `failed`), `stats` (jsonb), `error` |
| `costs` | `id`, `run_id`, `provider`, `model`, `task`, `input_tokens`, `output_tokens`, `calls`, `usd`, `inr`, `at` |
| `llm_batches` | `id`, `provider`, `provider_batch_id`, `task`, `status`, `item_count`, `submitted_at`, `completed_at`, `result_ref` |
| `source_health` | `source` (pk), `enabled`, `last_ok_at`, `last_error_at`, `last_error`, `blocked_until`, `requests_today` |
| `sheet_snapshots` | `sheet` (`master`, `caller`), `lead_id`, `values` (jsonb), `written_at`. Primary key (`sheet`, `lead_id`) |
| `golden_labels` | `id`, `business_id`, `label` (`good`, `bad`), `reasons`, `labeled_by`, `at` |
| `profiles` | `user_id` (pk, references `auth.users`), `full_name`, `role` (`admin`, `caller`, `viewer`), `created_at` |
| `custom_queries` | `id`, `segment_id`, `query`, `status`, `created_by`, `created_at` |
| `inbox_posts` | `id`, `url`, `text`, `segment_id`, `status`, `created_by`, `created_at` |

### A.12.2 Lead stages
Stored in snake case in the database, shown with the display label in the app and sheet.

| DB value | Display label | Closed? | Sheet colour (bg / text) |
|---|---|---|---|
| `new` | New | no | `#F2F2F2` / `#525252` |
| `contacted` | Contacted | no | `#E8EFFC` / `#212191` |
| `talking` | Talking | no | `#D2DFF9` / `#11115B` |
| `discovery_booked` | Discovery booked | no | `#FCEAF0` / `#9D2055` |
| `discovery_done` | Discovery done | no | `#F9D5E1` / `#871F4B` |
| `proposal_sent` | Proposal sent | no | `#FFF0CF` / `#8A5A00` |
| `won` | Won | yes (success) | `#E3F1D8` / `#385418` |
| `retainer` | Retainer | yes (success) | `#D9F0EA` / `#0F5C52` |
| `lost` | Lost | yes | `#FDE7E2` / `#A21913` |
| `not_now` | Not now | yes (re-check in 30 days) | `#FEEDE6` / `#A5460F` |
| `not_a_fit` | Not a fit | yes | `#F5F5F5` / `#999999` |
| `wrong_contact` | Wrong contact | yes (find the right number) | `#F3EEE8` / `#7A5536` |

### A.12.3 Signal types
| Type | Category | Example | Default points | Fresh for |
|---|---|---|---|---|
| `public_ask` | stated_need | "Looking for a developer to build a WhatsApp bot for our clinic" | 10 | 14 days |
| `tender` | stated_need | An RFP or tender for software, website, automation | 10 | until the deadline |
| `hiring_builder` | stated_need | Job post for a developer, automation or AI person | 8 | 30 days |
| `hiring_frontdesk` | visible_pain | Job post for receptionist, telecaller, patient coordinator, admissions counsellor, sales executive | 8 | 30 days |
| `review_pain` | visible_pain | Reviews mention unanswered calls, slow replies, booking trouble | 6 | 90 days |
| `ads_running` | visible_pain | Entered by hand in the app after checking ad libraries | 4 | while live (re-check 30 days) |
| `no_booking` | visible_pain | Website has no online booking and no WhatsApp or chat button | 3 | until fixed (re-check 60 days) |
| `slow_site` | visible_pain | Mobile speed score under 40 | 2 | 60 days |
| `new_place` | growth | A new business appeared in a monthly map release | 5 | 60 days |
| `new_branch` | growth | Careers, locations or news show a new branch | 5 | 60 days |
| `news` | growth | Launch, expansion, award in the news | 3 | 30 days |
| `funding` | money | Raised money (proof they can pay, not a need on its own) | 0 points of intent, +6 can-pay | 120 days |

### A.12.4 Pitch modes and test groups
- `pitch_mode`: `stated_need` (any active stated_need signal), `visible_pain` (no stated need, but at least one visible_pain signal), `fit_only` (no active signal; a small control group).
- `test_group` format: `{segment_id}:{pitch_mode}:{angle}`, for example `clinics-in:visible_pain:missed_calls`. Fit-only leads are capped at 10% of each day's leads.

### A.12.5 AI task names (see `engine/config/tasks.yaml`)
`classify_signal`, `classify_news`, `classify_page_change`, `extract_facts`, `verify_flagged`, `judge_lead`, `write_message`, `check_message`, `grounded_search`, `weekly_audit`.

### A.12.6 CLI commands (`nlead`)
Global flags on every command: `--env dev|prod`, `--segment ID` (repeatable), `--limit N`, `--dry-run`.

| Command | What it does |
|---|---|
| `nlead universe [--monthly]` | Build or refresh the universe from Overture, Places, registries |
| `nlead signals` | Run all signal watchers |
| `nlead prefilter` | Apply rules, build today's research queue |
| `nlead research` | Crawl queued businesses, store pages, detect tech |
| `nlead extract submit` / `nlead extract collect` | Submit / collect the AI fact extraction batch |
| `nlead verify` | Re-check quotes, phones, websites |
| `nlead score` | Compute scores and grades |
| `nlead judge` | Top-model judgement for the top half |
| `nlead message` | Write, lint and check messages |
| `nlead sheet push` / `nlead sheet pull` / `nlead sheet sync` | Sheet sync (sync = pull then push) |
| `nlead learn` / `nlead report weekly` / `nlead audit` | Learning, weekly report, weekly audit |
| `nlead eval [--subset N]` | Run the golden-set evaluation |
| `nlead health` | Check every service and source |
| `nlead backup` | Encrypted database dump |
| `nlead migrate-legacy` | One-time import from the old `lead-engine` folder |
| `nlead run night` / `nlead run morning` / `nlead run sheet` / `nlead run weekly` / `nlead run monthly` | Orchestrated runs used by GitHub Actions |

### A.12.7 Environment variables
| Variable | Used by | Secret? |
|---|---|---|
| `APP_ENV` | engine, web | no (`dev` or `prod`) |
| `DATABASE_URL` | engine | yes (Supabase session pooler, port 5432) |
| `SUPABASE_URL` | engine, web server | no |
| `SUPABASE_SERVICE_ROLE_KEY` | engine, web server only | yes, never in the browser |
| `NEXT_PUBLIC_SUPABASE_URL` | web browser | no |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | web browser | no (protected by RLS) |
| `GEMINI_API_KEY` | engine | yes |
| `OPENAI_API_KEY` | engine | yes |
| `GOOGLE_MAPS_API_KEY` | engine | yes (Places API New + PageSpeed Insights) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | engine in CI | yes (full JSON) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | engine locally | path only |
| `SHEET_MASTER_ID`, `SHEET_CALLER_ID`, `SHEET_STAGING_ID` | engine | no |
| `ASSOCIATE_NAME` | engine | no (`Aditya`) |
| `USER_AGENT` | engine | no (`NumentLeadBot/1.0 (+https://nument.in)`) |
| `GH_DISPATCH_TOKEN` | web server | yes (fine-grained token, Actions write on this repo only) |
| `BACKUP_PASSPHRASE` | engine in CI | yes |
| `ALERT_EMAIL` | engine | no (optional) |

### A.12.8 Segment ids (wave 1)
`clinics-in`, `realestate-in`, `education-in`, `clinics-ae`, `realestate-ae`, `education-ae`.

### A.12.9 Score scale and grades
- `total` is 0 to 100.
- Grades: **A** at 70 or more, **B** 55 to 69, **C** 40 to 54, **D** under 40.
- A and B become leads. C waits for a new signal. D is dropped for 90 days.

---

## A.13 Reconciled names and later additions

Steps were written in parallel. This section is the final word wherever two steps disagree.

### A.13.1 AI output models (canonical names)
| Model | Used by task | The step that defines its fields |
|---|---|---|
| `SignalClassification` | `classify_signal` | Step 7 (and Step 4.x shows the router contract) |
| `NewsClassification` | `classify_news` | Step 5 (GDELT adapter) |
| `PageChangeClassification` | `classify_page_change` | Step 5 (careers watcher) |
| `FactsExtraction` | `extract_facts` | Step 9.7 |
| `FlaggedVerification` | `verify_flagged` | Step 10 |
| `LeadJudgement` | `judge_lead` | Step 11 |
| `MessageDraft` | `write_message` | Step 12 |
| `MessageCheck` | `check_message` | Step 12 |
| `PublicAskResults` (items: `PublicAskItem`) | `grounded_search` | Step 5 |
| `AuditResult` | `weekly_audit` | Step 17 |

Rule: where two steps show the same model with different fields, the step in the right-hand column wins, and the prompt in Appendix A is updated to match it.

### A.13.2 Fact field names
- Per-row `facts.field` values come from Step 9: `business_name`, `decision_maker`, `phone`, `email`, `branches`, `staff_or_doctors`, `service`, `price_point`, `booking_method`, `whatsapp_present`, `chat_widget`, `careers_role`, `in_house_tech`, `is_agency_or_vendor`, `language`, `sales_note`.
- Code-derived facts (`model = 'rule'`): `jsonld_phone`, `jsonld_email`, `jsonld_name`, `jsonld_price_range`, `jsonld_employees`, `jsonld_job`, `tech_stack`, `site_speed_mobile`, `careers_url`, `locations_url`, `website_status`, `contact_form_url`.
- Verified facts roll up into business columns: `branches` becomes `businesses.branches_count`, and `staff_or_doctors` becomes `businesses.staff_count`. Scoring (Step 11) reads the business columns.

### A.13.3 Migration files
| File | Defined in | Contents |
|---|---|---|
| `0001_core.sql` to `0004_seed.sql` | Step 2 | Core tables, views, RLS, seed |
| `0005_sheet_views.sql` | Step 13 | `v_sheet_leads` |
| `0006_cost_views.sql` | Step 19 | `v_spend_today`, `v_quota_today`, `v_quota_month` (skip any view Step 2 already made) |
| `0007_learning.sql` | Step 16 | `weight_versions`, `reports`, `v_lead_funnel` |
| `0008_llm.sql` | Step 4 | `llm_cache`, `llm_batch_reservations`, `costs.fallback_from` |

### A.13.4 Other additions from later steps
- Repository: `github.com/with-nument/nument-lead` (private). The local folder stays `nument-leads`.
- Database: one Supabase project for now (`nument-lead-gen`, Sydney) used as both dev and prod until a second project exists. Tests run against a temporary local Postgres (Step 17), never against this project's real data.
- Web: Next.js 16 renamed `middleware.ts` to `proxy.ts`. Use whichever name your installed Next.js version expects. Tailwind v4 keeps the theme in `globals.css` (`@theme`), so `tailwind.config.ts` is only needed on Tailwind v3.
- Auth: public sign-up is off. Only an admin creates users (Step 15). The first admin is the founder. New users must change their password on first login.
- Settings keys added by later steps: `segment_weights`, `score_weights`, `score_weights_frozen`, `sheet_state`, `send_per_day`, `today_rows_max`, `weekly_contact_target`, `budget_alert_day`, `places_details_daily_cap`, `places_reviews_daily_cap`, `places_details_daily_cap_global`, `grounding_daily_cap`, `pagespeed_daily_cap`, `overture_release`, plus per-source daily limits (`careers_watch.pages_per_day`, `grounded_search.per_day`, `gdelt.queries_per_day`, `ai.classify_per_day`, `research.browser_pages_per_run`, `practo.pages_per_day`).
- Activity types used across steps: `lead_created`, `stage_change` (payload `{from, to}`), `grade_change`, `message_flagged`, `message_edited`, `sent`, `followup_sent`, `call`, `meeting`, `proposal`, `proposal_upload`, `note`, `edit`, `skip`, `wrong_contact`, `feedback`, `regen_request`, `undo`, `merge`, `won`, `conflict_overridden`, `unknown_stage`, `ai_output`.
- Extra environment variables: `NEXT_PUBLIC_APP_URL`, `GH_REPO`, `GH_DISPATCH_REF`, `GEMINI_API_KEY_BACKUP` (second Gemini key, used when the first hits its quota), optional `RESEND_API_KEY`, and the CI secret `DEV_DATABASE_URL`.

---

### A.13.5 Final rules where steps disagree (apply these first)
1. **Activity rows:** database triggers (Step 2) write `lead_created`, `stage_change`, `grade_change` and `message_edited`. Application code (Steps 11, 13, 15) must not insert those four types again; it only sets the transaction context `app.source` and `app.context` through `db.tx(source, context)` so the trigger records who made the change.
2. **No money leaks through views:** every view uses `with (security_invoker = true)` except `v_leads_admin`. This includes Step 13's `v_sheet_leads` and Step 19's cost views. Step 19 must not recreate `v_costs_daily` (Step 2 owns it).
3. **Migration numbers:** as in A.13.3 (`0005_sheet_views`, `0006_cost_views`, `0007_learning`, `0008_llm`). Tables Step 2 already creates (`llm_cache`, `llm_batch_reservations`, `costs.fallback_from`, `saved_views`) are skipped in later migrations with `if not exists`.
4. **Cost providers:** Places calls are logged with provider `google_places`, grounded search with `google_search`, PageSpeed with `pagespeed`, cache hits with `cache`.
5. **OpenAI starts off:** `providers_enabled.openai = false` by default everywhere (seed, Step 4 text, tests).
6. **One exclusions file shape:** the shape defined in Step 3.6 is the only one. Steps 8, 10 and Appendix D read it through the Step 3 loader.
7. **Subcategories and ticket classes:** use the Step 3 names (`ivf_fertility`, `hair_transplant`, `aesthetic`, `dermatology`, `dental`, `physio`, `therapy_group`, `developer`, `broker`, `property_services`, `study_abroad`, `coaching_institute`, `academy`, `tutoring`). The IVF registry adapter sets the subcategory from `registries[].subcategory`, never a hard-coded `'ivf'`.
8. **Scoring reads config:** Step 11 reads every weight (fit bonus, stacking bonus, reach multipliers, grade thresholds) from `scoring_config(segment)`, which merges `engine/config/scoring.yaml`, segment overrides and `settings.score_weights`.
9. **Inbox and custom query statuses:** `new`, `processing`, `researched`, `lead_created`, `rejected`.
10. **Fact field names:** Step 9 names (A.13.2) everywhere, including the Appendix A prompts.
11. **Daily quota:** after the first seed, `segments.daily_quota` in the database is the source of truth (the app edits it). Step 8 reads the database value.
12. **Backups:** dump only the `public` schema (`pg_dump --schema=public`), compress and encrypt, and keep files under the storage upload limit (verify at build). Restores go into a fresh project after running the migrations.
13. **Database size on the free tier (500 MB):** keep raw page text for 30 days only (90 days for businesses that became leads), store page text trimmed to 20,000 characters, and keep facts, signals and leads for good. `nlead health` warns at 350 MB. Upgrading Supabase is a founder decision.

---

# Step 0: Accounts, access and machine setup

## 0.1 Goal, owner and time

| Field | Value |
|---|---|
| Goal | Every account, key, quota and tool is ready before any code is written |
| Owner | Founder creates accounts and adds cards (identity and payment). Builder configures everything else |
| Time | 2 to 3 hours in total |
| Needs first | A password manager (1Password, Bitwarden or Apple Passwords). Every secret in this step goes there first |

Labels used below:
- **Founder:** must be done by the founder (owns the account, card or identity).
- **Builder:** can be done by whoever builds the system.

## 0.2 GitHub

### 0.2.1 Create the private repository (Founder)
1. Open https://github.com/new.
2. Owner: the `with-nument` organisation (where the `nument-landing` website repo already lives).
3. Repository name: `nument-leads`.
4. Visibility: **Private**.
5. Do **not** add a README, .gitignore or licence. We push our own in Step 1.
6. Click **Create repository**.

### 0.2.2 Give the builder access (Founder)
1. Repo, **Settings**, **Collaborators and teams**, **Add people**.
2. Add the builder's GitHub username with the **Write** role.

### 0.2.3 Turn on GitHub Actions (Founder)
1. Repo, **Settings**, **Actions**, **General**.
2. Actions permissions: **Allow all actions and reusable workflows**.
3. Workflow permissions: **Read repository contents and packages permissions**.
4. Check the minutes allowance: organisation **Settings**, **Billing and plans**. The free plan includes about 2,000 Linux minutes a month for private repos (verify at build). Step 14.6 keeps us inside it.

### 0.2.4 Create GitHub environments (Builder)
Environments let the same workflow use dev or prod secrets.
1. Repo, **Settings**, **Environments**, **New environment**: create `dev`.
2. Create `prod`. Optional: tick **Required reviewers** and add the founder, so manual prod runs need approval.
3. Secrets and variables are added per environment in 0.10.

### 0.2.5 Fine-grained token for the web app (Founder)
The web app's "Run now" button (Step 15) triggers a workflow through the GitHub API. It needs a narrow token.
1. https://github.com/settings/personal-access-tokens/new (fine-grained token).
2. Name: `nument-leads-dispatch`. Expiry: 1 year (calendar reminder to renew).
3. Resource owner: `with-nument`. Repository access: **Only select repositories**, `nument-leads`.
4. Permissions: **Actions: Read and write**, **Contents: Read-only**, **Metadata: Read-only** (default). Nothing else.
5. Generate, copy into the password manager as `GH_DISPATCH_TOKEN`. It goes to Render only (0.10), never into the repo.

### 0.2.6 Secret scanning (Builder)
1. Repo, **Settings**, **Code security**: enable **Secret scanning** and **Push protection** if your plan offers them for private repos (verify at build; some features need GitHub Advanced Security).
2. Either way, Step 1 adds a local `gitleaks` check as a second line of defence.

## 0.3 Supabase

### 0.3.1 Account and organisation (Founder)
1. Sign up at https://supabase.com with the founder's email. Turn on two-factor authentication (**Account**, **Security**).
2. Create an organisation named `Nument`, plan **Free**.

### 0.3.2 Create the dev project (Founder)
1. **New project**.
2. Name: `nument-leads-dev`.
3. Database password: generate a strong one, save it in the password manager as `SUPABASE_DEV_DB_PASSWORD`.
4. Region: **South Asia (Mumbai)** (`ap-south-1`).
5. Plan: Free. Create.

### 0.3.3 Create the prod project (Founder)
Repeat 0.3.2 with name `nument-leads-prod` and password `SUPABASE_PROD_DB_PASSWORD`. Same region.

### 0.3.4 Free-tier limits to know (verify at build)
| Limit | Free tier | What it means for us |
|---|---|---|
| Projects | 2 active free projects per organisation | Exactly dev + prod |
| Database size | 500 MB | Raw page text is pruned after 90 days (Step 18) |
| File storage | 1 GB | Proposal PDFs uploaded in the app |
| Monthly active users (auth) | 50,000 | We have 2 to 5 users |
| Pausing | Paused after 7 days without activity | Nightly runs keep both projects active. A paused dev project is restored with one click |
| Backups | No point-in-time recovery | Our own weekly encrypted dump (Step 2 and Step 14) |

### 0.3.5 Connection strings (Builder)
Do this for **both** projects.
1. Project, **Connect** button (top bar), or **Project Settings**, **Database**.
2. You will see three options:
   - **Direct connection** (`db.<ref>.supabase.co:5432`): IPv6 only on the free plan. **GitHub Actions runners do not support IPv6, so do not use this.**
   - **Session pooler** (Supavisor, port **5432**, IPv4): **use this** for the engine. It supports long jobs and prepared statements.
   - **Transaction pooler** (port 6543): not used. If you ever use it, set `prepare_threshold=None` in psycopg, because it does not support prepared statements.
3. Copy the session pooler URI. It looks like this (host differs per project, copy it from the dashboard):
   ```
   postgresql://postgres.<project-ref>:<db-password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```
4. Save as `DATABASE_URL` (dev) and `DATABASE_URL` (prod) in the password manager, clearly labelled.

### 0.3.6 API keys (Builder)
For both projects: **Project Settings**, **API** (or **API Keys**).
| Value | Saved as | Notes |
|---|---|---|
| Project URL | `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL` | Same value, two names |
| `anon` public key (or the newer **publishable** key) | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Safe in the browser because RLS protects data |
| `service_role` key (or the newer **secret** key) | `SUPABASE_SERVICE_ROLE_KEY` | Bypasses RLS. Engine and web server only. Never in the browser, never in a `NEXT_PUBLIC_` variable |

Supabase has been moving from `anon`/`service_role` keys to `sb_publishable_...`/`sb_secret_...` keys (verify at build). Either works; keep the names above in our env vars.

### 0.3.7 Auth settings (Builder, both projects)
1. **Authentication**, **Sign In / Providers**, **Email**: enabled.
2. **Allow new users to sign up: OFF.** The app is invite only (Step 15 adds users from the admin page or the dashboard).
3. **Confirm email: ON.**
4. **Minimum password length: 12.** Password requirements: letters and digits (or stronger).
5. **URL Configuration**:
   - Dev project: Site URL `http://localhost:3000`, redirect URLs `http://localhost:3000/**`.
   - Prod project: Site URL is the Render URL (or `https://leads.nument.in` if you set up the subdomain in 0.8), redirect URLs the same with `/**`.
6. Email sending: the built-in Supabase mailer has a low hourly limit (verify at build). That is fine for a handful of invites and password resets. A custom SMTP sender can be added later if needed.

### 0.3.8 Install nothing else yet
Tables, RLS policies, storage buckets and seed data are all created by migrations in Step 2. Do not click them together in the dashboard, or dev and prod will drift.

## 0.4 Render

### 0.4.1 Account (Founder)
1. Sign up at https://render.com using **GitHub login**.
2. Turn on two-factor authentication.
3. When Render asks for GitHub access, grant it to the `with-nument` organisation, **Only select repositories**, `nument-leads`.

### 0.4.2 Plan choice (Founder, decided at go-live)
| Plan | Cost (verify at build) | Behaviour |
|---|---|---|
| Free web service | $0 | Sleeps after 15 minutes idle; the first load after sleep takes 30 to 60 seconds |
| Starter | About $7 a month | Always on, no cold starts |
Region: **Singapore** (closest to India). Nothing is deployed until Step 15.

### 0.4.3 Billing (Founder)
Add a card only if Starter is chosen.

## 0.5 Google Cloud (existing project `lead-engine-510307`)

This project already holds the service account that writes the two Google Sheets.

### 0.5.1 Open the project (Founder)
https://console.cloud.google.com, top bar project picker, select **lead-engine-510307**.

### 0.5.2 Billing and a budget alert (Founder)
1. Menu, **Billing**, **Link a billing account**, **Create billing account** (India, INR, card). Google may charge about ₹2 to verify the card.
2. **Billing**, **Budgets and alerts**, **Create budget**: amount ₹500 a month, alerts at 50%, 90%, 100% to the founder's email.
3. Remember: budgets only **notify**. The **quotas** in 0.5.5 are what actually stop spend.

### 0.5.3 Enable APIs (Builder)
**APIs and Services**, **Library**, search and **Enable**:
| API | Service name | Why |
|---|---|---|
| Places API (New) | `places.googleapis.com` | Business lists, rating, review count, website, phone, reviews |
| PageSpeed Insights API | `pagespeedonline.googleapis.com` | Mobile speed score of websites |
| Google Sheets API | `sheets.googleapis.com` | Already enabled for the current sheets. Confirm |
| Google Drive API | `drive.googleapis.com` | Already enabled. Confirm |

Do **not** enable the legacy "Places API". New projects cannot use it and our client library targets the new one.

### 0.5.4 API key (Builder)
1. **APIs and Services**, **Credentials**, **Create credentials**, **API key**.
2. Rename it `nument-leads-engine`.
3. **API restrictions**: **Restrict key**, tick **Places API (New)** and **PageSpeed Insights API**. Nothing else.
4. **Application restrictions**: None. (GitHub Actions runners have changing IP addresses, so an IP restriction would break the nightly run. The API restriction above limits the damage if the key leaks.)
5. Save. Copy into the password manager as `GOOGLE_MAPS_API_KEY`.

### 0.5.5 Daily quotas (Builder)
**APIs and Services**, **Places API (New)**, **Quotas and System Limits**. Find the per-day request quotas and edit (metric names verify at build):
| Method | Per-day cap | Reason |
|---|---|---|
| Text Search (`SearchText`) | 3,000 | ID-only search is free and unlimited, but a cap protects against a loop bug |
| Place Details (`GetPlace`) | 460 | 230 a day for the Enterprise SKU plus 230 for Enterprise + reviews keeps both inside the 7K free a month in India. The engine splits the two SKUs itself (Step 19) |
| Any other Places method | 0 | We do not use autocomplete, photos or nearby search |

For PageSpeed Insights, leave the default quota (it is free; 25K a day is commonly reported, verify at build).

### 0.5.6 Rotate the service account key (Builder, with Founder)
The current key was pasted in a chat in October and must be replaced.
1. **IAM and Admin**, **Service accounts**. Find the account in the old repo at `~/Desktop/lead-engine/data/sheet.json` (field `service_account`).
2. **Keys**, **Add key**, **Create new key**, **JSON**. A file downloads.
3. Move it to `~/.config/nument-leads/service-account.json`, then:
   ```bash
   mkdir -p ~/.config/nument-leads
   mv ~/Downloads/lead-engine-510307-*.json ~/.config/nument-leads/service-account.json
   chmod 600 ~/.config/nument-leads/service-account.json
   ```
4. The old engine still runs every morning at 8:00 from `~/.config/lead-engine/service-account.json` until the Step 20 cutover. Copy the new key over the old path too, then **delete the old key** in the console (Keys tab, trash icon):
   ```bash
   cp ~/.config/nument-leads/service-account.json ~/.config/lead-engine/service-account.json
   chmod 600 ~/.config/lead-engine/service-account.json
   ```
5. Run the old sync once to prove the new key works: `cd ~/Desktop/lead-engine && .venv/bin/python scripts/sync_sheet.py`. It must finish with `synced master, caller`.
6. The full JSON will also become the GitHub secret `GOOGLE_SERVICE_ACCOUNT_JSON` (0.10).

### 0.5.7 Sheets (Founder)
1. The two live sheets keep their IDs. Read them from `~/Desktop/lead-engine/data/sheet.json` (`spreadsheet_id` is the master "Leads-main", `caller_spreadsheet_id` is "Leads-Associate"). Save them as `SHEET_MASTER_ID` and `SHEET_CALLER_ID`.
2. Confirm both are shared with the service account email as **Editor** (Share button). They already are; just check.
3. Create a new empty Google Sheet named **Leads-staging** in the founder's Drive. Share it with the service account email as **Editor**. Copy its ID from the URL (`https://docs.google.com/spreadsheets/d/<ID>/edit`) as `SHEET_STAGING_ID`. All dev runs write here, never to the live sheets.

## 0.6 Gemini API

### 0.6.1 Key on a paid tier (Founder)
1. https://aistudio.google.com, **Get API key**.
2. Create the key inside a Google Cloud project **with billing enabled** (the same `lead-engine-510307` is fine). This makes it a paid-tier key.
3. Why paid: on the free tier Google may use prompts and responses to improve its products, and rate limits are low (verify the current terms at build). Our prompts contain business data, so we use the paid tier.
4. The founder's existing `GEMINI_API_KEY` in `~/Desktop/lead-engine/.env.local` can be reused only if AI Studio shows it on a **paid** project. Otherwise create a new one. Save as `GEMINI_API_KEY`.

### 0.6.2 Record the exact model IDs (Builder)
Model names change every few months. List what the key can use and write the exact IDs into `engine/config/tasks.yaml` in Step 4:
```bash
curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY&pageSize=200" \
  | jq -r '.models[] | select(.supportedGenerationMethods | index("generateContent")) | .name'
```
You need one ID each for: a Flash-Lite model, a Flash model and a Pro model (Gemini 3.x at the time of writing, verify at build). Also confirm the batch method is supported (`batchGenerateContent` appears in `supportedGenerationMethods`).

### 0.6.3 Second spending guard (Founder)
In Google Cloud **Billing**, add a separate budget for Gemini usage of ₹15,000 a month with alerts. The engine's own ₹750 a day cap (Step 19) is the main guard; this is a backstop.

## 0.7 OpenAI

### 0.7.1 Project key (Founder)
1. https://platform.openai.com, top left project picker, **Create project**: `nument-leads`.
2. Inside it: **API keys**, **Create new secret key**, owned by the project. Save as `OPENAI_API_KEY`.
3. Do not reuse the old key in `~/Desktop/lead-engine/.env.local` unless it is already a project key for this project.

### 0.7.2 Limits (Founder)
1. **Settings**, **Limits** (project level): monthly budget about $60 with an email alert at 80% (verify the menu names at build).
2. **Model access** for the project: allow only the models in `tasks.yaml` (GPT-5 mini and GPT-5 nano for the Balanced tier, verify exact IDs at build).
3. **Billing**: add prepaid credits (minimum $5) or a card.

## 0.8 Optional: subdomain `leads.nument.in` (Founder, after Step 15)
1. GoDaddy, **DNS** for `nument.in`, **Add record**: type **CNAME**, name `leads`, value `<render-service-name>.onrender.com`, TTL 1 hour.
2. In Render, service **Settings**, **Custom domains**, add `leads.nument.in`. Render issues the TLS certificate automatically.
3. Leave the existing records alone: `A @ 216.198.79.1`, `CNAME www`, and the `TXT google-site-verification` record used by Search Console.
4. Update the prod Supabase Site URL and redirect URLs (0.3.7) to `https://leads.nument.in`.

## 0.9 Local machine setup (macOS)

### 0.9.1 Check what is installed (Builder)
```bash
node -v        # need 22 or newer
pnpm -v        # need 9 or newer
uv --version   # any recent version
git --version
python3 --version
```
State of the founder's Mac on 12 Nov 2026: Node 24.16, pnpm 11.5, uv 0.12.19, git 2.50, system Python 3.14. All fine. Python 3.12 for the engine is installed through uv, not system-wide.

### 0.9.2 Install anything missing
```bash
brew install node pnpm uv git
```

### 0.9.3 Python 3.12 through uv
```bash
uv python install 3.12
uv python list | grep 3.12
```
Why not 3.14: some dependencies (duckdb, pyarrow, playwright) publish wheels for new Python versions late. 3.12 is the safe choice (verify at build; move up once all wheels exist).

### 0.9.4 Supabase CLI without installing it
```bash
npx supabase@latest --version
```
We never run Supabase locally, so **Docker is not needed**. All development uses the remote `nument-leads-dev` project.

### 0.9.5 Optional tools
```bash
brew install gh jq gitleaks
gh auth login     # the person runs this themselves; never paste tokens into chats
```

### 0.9.6 Editor
VS Code or Cursor with these extensions: Python, Ruff, ESLint, Tailwind CSS IntelliSense, EditorConfig.

## 0.10 Secrets inventory

Where each variable from A.12.7 lives. "Var" means a GitHub Actions **variable** (not secret). `dev` and `prod` refer to the GitHub environments from 0.2.4.

| Variable | Local engine (`engine/.env.dev`, `engine/.env.prod`) | Local web (`web/.env.local`) | GitHub Actions | Render | Value comes from |
|---|---|---|---|---|---|
| `APP_ENV` | `dev` or `prod` per file | no | Var per environment (`dev`, `prod`) | `prod` | Fixed |
| `DATABASE_URL` | dev pooler URI / prod pooler URI | no | Secret in `dev` and `prod` | no | 0.3.5 |
| `SUPABASE_URL` | yes | no | Secret in `dev` and `prod` | yes | 0.3.6 |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | yes (server code only) | Secret in `dev` and `prod` | yes | 0.3.6 |
| `NEXT_PUBLIC_SUPABASE_URL` | no | yes | Secret in `dev` (for CI build) | yes | 0.3.6 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | no | yes | Secret in `dev` (for CI build) | yes | 0.3.6 |
| `GEMINI_API_KEY` | yes | only if Step 15 enables in-app AI | Secret in `dev` and `prod` | only if Step 15 says so | 0.6.1 |
| `OPENAI_API_KEY` | yes | only if Step 15 enables in-app AI | Secret in `dev` and `prod` | only if Step 15 says so | 0.7.1 |
| `GOOGLE_MAPS_API_KEY` | yes | no | Secret in `dev` and `prod` | no | 0.5.4 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | no (use the file below) | no | Secret in `dev` and `prod` (full JSON text) | no | 0.5.6 |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `~/.config/nument-leads/service-account.json` | no | no | no | 0.5.6 |
| `SHEET_MASTER_ID` | prod file only | no | Var in `prod` | no | 0.5.7 |
| `SHEET_CALLER_ID` | prod file only | no | Var in `prod` | no | 0.5.7 |
| `SHEET_STAGING_ID` | both files | no | Var in `dev` and `prod` | no | 0.5.7 |
| `ASSOCIATE_NAME` | `Aditya` | no | Var | no | Fixed |
| `USER_AGENT` | `NumentLeadBot/1.0 (+https://nument.in)` | no | Var | no | Fixed |
| `GH_DISPATCH_TOKEN` | no | yes (only to test "Run now" locally) | no | yes | 0.2.5 |
| `BACKUP_PASSPHRASE` | no | no | Secret in `prod` | no | Generate a 32+ character passphrase, keep it in the password manager. Without it backups cannot be restored |
| `ALERT_EMAIL` | optional | no | Var (optional) | no | Founder's email |

Adding a secret on GitHub: repo, **Settings**, **Environments**, pick `dev` or `prod`, **Add environment secret**. Variables: same page, **Add environment variable**.

Adding env vars on Render: service, **Environment**, **Add environment variable** (Step 15 creates the service).

In dev, `SHEET_MASTER_ID` and `SHEET_CALLER_ID` are deliberately **unset**. The engine refuses to write to a live sheet when `APP_ENV=dev` (enforced in `settings.py`, Step 1.4.5).

## 0.11 Security basics

1. **Two-factor authentication** on GitHub, Supabase, Render, Google and OpenAI accounts.
2. **Secrets live only in four places:** the password manager, local env files (permission 600), GitHub environment secrets, Render environment variables. Never in code, never in chat, never in a commit.
3. **Least privilege:** the Maps key is limited to two APIs; the OpenAI key is a project key with a budget; the GitHub token is fine-grained to one repo; the Supabase service role key never reaches the browser.
4. **Rotations still pending from October (do them now):**
   - Google service account key: done in 0.5.6.
   - The old GitHub personal access token that was pasted in chat: revoke it at https://github.com/settings/tokens.
5. **If a key leaks:** revoke it in the provider's console first, create a new one, update the password manager, GitHub secrets and Render, then re-run the last failed job.
6. **Review access every 3 months:** collaborators, Render members, Supabase members, Google IAM.

## 0.12 Done when
- [ ] Private repo `with-nument/nument-lead` exists, Actions enabled, environments `dev` and `prod` created.
- [ ] Fine-grained `GH_DISPATCH_TOKEN` created and stored in the password manager.
- [ ] Supabase `nument-leads-dev` and `nument-leads-prod` exist in Mumbai, sign-ups off, confirm email on, password length 12.
- [ ] Session pooler `DATABASE_URL`, URL, anon key and service role key saved for both projects.
- [ ] Render account exists and can see the `nument-leads` repo.
- [ ] Google Cloud billing on, ₹500 budget alert set, Places API (New) and PageSpeed Insights API enabled, restricted `GOOGLE_MAPS_API_KEY` created, daily quotas set.
- [ ] New service account key in `~/.config/nument-leads/service-account.json`, old key deleted, old engine still syncs.
- [ ] `Leads-staging` sheet created and shared; three sheet IDs saved.
- [ ] Paid-tier `GEMINI_API_KEY` saved, exact Flash-Lite, Flash and Pro model IDs written down.
- [ ] Project-scoped `OPENAI_API_KEY` saved, monthly budget and alert set.
- [ ] Node 22+, pnpm, uv with Python 3.12, git working locally; `npx supabase --version` works.
- [ ] Every secret from 0.10 is in the password manager.
- [ ] Old GitHub token revoked.

---

---

# Step 1: Repository and project skeleton

## 1.1 Goal, owner and time

| Field | Value |
|---|---|
| Goal | An empty but runnable monorepo: the engine CLI prints help, the web app renders a page, CI passes on GitHub |
| Owner | Builder |
| Time | 4 to 6 hours |
| Needs first | Step 0 done |

## 1.2 Create the repository locally

### 1.2.1 Folder
The folder `~/Desktop/nument-leads` already exists and holds this plan.
```bash
cd ~/Desktop/nument-leads
git init -b main
git remote add origin https://github.com/with-nument/nument-lead.git
```

### 1.2.2 Git identity
Commits are made under the founder's GitHub identity (the founder's preference). Do **not** add AI co-author trailers to commit messages.
```bash
git config user.name  "<founder's GitHub display name>"
git config user.email "<founder's GitHub noreply email>"
```

### 1.2.3 Folders
```bash
mkdir -p .github/workflows supabase engine web docs
```

## 1.3 Root files

### 1.3.1 `.gitignore`
```gitignore
# ---- secrets and env ----
.env
.env.*
!.env.example
**/.env.dev
**/.env.prod
**/.env.local
service-account*.json
*.pem
*.key

# ---- python ----
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
dist/
build/

# ---- node / next ----
node_modules/
web/.next/
web/out/
.pnpm-store/
*.tsbuildinfo
next-env.d.ts

# ---- playwright ----
web/test-results/
web/playwright-report/
web/blob-report/
playwright/.cache/

# ---- supabase ----
supabase/.temp/
supabase/.branches/

# ---- engine data and caches (never commit raw data) ----
engine/.cache/
engine/data/
*.parquet
*.duckdb
*.sql.gz
*.gpg

# ---- os and editors ----
.DS_Store
.idea/
.vscode/*
!.vscode/extensions.json
```

### 1.3.2 `.editorconfig`
```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 2
trim_trailing_whitespace = true

[*.py]
indent_size = 4

[*.md]
trim_trailing_whitespace = false
```

### 1.3.3 `.env.example`
Copy this file to `engine/.env.dev`, `engine/.env.prod` and `web/.env.local`, then fill in only the variables each one needs (table 0.10).
```bash
# ===== nument-leads: every environment variable (no values here, ever) =====

# dev | prod. The engine refuses to touch live sheets when this is dev.
APP_ENV=dev

# ---- Supabase ----
# Session pooler URI (IPv4, port 5432). Never the direct connection.
DATABASE_URL=
SUPABASE_URL=
# Bypasses RLS. Engine and web server only. Never NEXT_PUBLIC.
SUPABASE_SERVICE_ROLE_KEY=
# Browser-safe values for the web app
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=

# ---- AI ----
GEMINI_API_KEY=
OPENAI_API_KEY=

# ---- Google ----
# Restricted to Places API (New) + PageSpeed Insights API
GOOGLE_MAPS_API_KEY=
# CI: full JSON text of the service account key. Local: leave empty and use the file path.
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SERVICE_ACCOUNT_FILE=~/.config/nument-leads/service-account.json

# ---- Sheets ----
# Live sheets: prod only. Leave empty in dev.
SHEET_MASTER_ID=
SHEET_CALLER_ID=
SHEET_STAGING_ID=

# ---- Behaviour ----
ASSOCIATE_NAME=Aditya
USER_AGENT=NumentLeadBot/1.0 (+https://nument.in)

# ---- Web app only ----
# Fine-grained token: Actions read/write on this repo only
GH_DISPATCH_TOKEN=

# ---- CI only ----
BACKUP_PASSPHRASE=
ALERT_EMAIL=
```
Then lock the local files down:
```bash
cp .env.example engine/.env.dev && cp .env.example engine/.env.prod && cp .env.example web/.env.local
chmod 600 engine/.env.dev engine/.env.prod web/.env.local
```

### 1.3.4 `README.md` (outline)
```markdown
# nument-leads
Standalone lead engine + web app for Nument. Full build manual: IMPLEMENTATION_PLAN.md.

## Layout
- engine/: Python engine (`nlead` CLI), runs nightly on GitHub Actions
- web/: Next.js app (Render), email + password login
- supabase/: database migrations
- .github/workflows/: CI and schedules
- docs/: runbook, data policy, segments guide

## Run locally
- Engine: `cd engine && uv sync && uv run nlead --env dev health`
- Web: `cd web && pnpm install && pnpm dev`, open http://localhost:3000

## Rules
Never commit secrets. Dev never writes to live sheets. See docs/data-policy.md.
```

### 1.3.5 `docs/` placeholders
```bash
printf "# Runbook\n\nFilled in Step 22.\n" > docs/runbook.md
printf "# Data policy\n\nFilled in Step 18 (copy of Part A.4 plus enforcement details).\n" > docs/data-policy.md
printf "# Segments guide\n\nFilled in Step 3 and Step 23.\n" > docs/segments-guide.md
```

### 1.3.6 Local secret scan before every commit (optional but recommended)
```bash
brew install gitleaks
gitleaks git --staged --redact   # run before each commit (command name verify at build: older versions use `gitleaks protect --staged`)
```

## 1.4 Engine project (Python)

### 1.4.1 Initialise with uv
```bash
cd ~/Desktop/nument-leads/engine
uv init --package --name nument-engine --python 3.12 .
uv python pin 3.12
```
This creates `pyproject.toml`, `src/nument_engine/__init__.py` and `.python-version`. Replace `pyproject.toml` with 1.4.2.

### 1.4.2 `engine/pyproject.toml` (full file)
Lower bounds below are safe minimums; `uv lock` pins the exact versions on the day you build (verify at build).
```toml
[project]
name = "nument-engine"
version = "0.1.0"
description = "Nument Leads engine: finds, researches, scores and writes leads"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
    "httpx[http2]>=0.27",
    "tenacity>=9.0",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "pyyaml>=6.0",
    "psycopg[binary,pool]>=3.2",
    "duckdb>=1.1",
    "pyarrow>=17.0",
    "playwright>=1.47",
    "trafilatura>=1.12",
    "extruct>=0.17",
    "selectolax>=0.3.21",
    "phonenumbers>=8.13",
    "tldextract>=5.1",
    "rapidfuzz>=3.9",
    "google-genai>=1.0",
    "openai>=1.50",
    "gspread>=6.1",
    "google-auth>=2.34",
    "jinja2>=3.1",
    "typer>=0.12",
    "rich>=13.8",
    "structlog>=24.4",
    "python-dateutil>=2.9",
]

[project.scripts]
nlead = "nument_engine.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/nument_engine"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.6",
    "mypy>=1.11",
    "types-PyYAML",
    "types-python-dateutil",
]

[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
warn_unused_ignores = true
check_untyped_defs = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "live: hits real APIs or the dev database (skipped in CI)",
]
```
Install:
```bash
uv sync
uv run playwright install chromium
```

### 1.4.3 Package skeleton (matches A.8)
```bash
cd ~/Desktop/nument-leads/engine
mkdir -p config segments prompts tests/fixtures evals/golden \
  src/nument_engine/{llm,sources,pipeline,research,sheet,learn,ops}
for d in llm sources pipeline research sheet learn ops; do touch src/nument_engine/$d/__init__.py; done
touch src/nument_engine/{settings,logging,db,models,segments,budget,http}.py
touch src/nument_engine/llm/{router,gemini,openai_provider,batch,prompts}.py
touch src/nument_engine/sources/{base,overture,places,art_registry,practo,apna,careers_watch,gdelt,grounded_search,osm,adzuna}.py
touch src/nument_engine/pipeline/{universe,resolve,signals,prefilter,research,extract,verify,score,judge,message,runs}.py
touch src/nument_engine/research/{pages,text,structured,techstack,quality}.py
touch src/nument_engine/sheet/{push,pull,design}.py
touch src/nument_engine/learn/{metrics,reweight,report}.py
touch src/nument_engine/ops/{health,backup,migrate_legacy}.py
touch config/{prices,tasks,exclusions}.yaml evals/run_eval.py
```
Note: `logging.py` inside the package shadows nothing because it is imported as `nument_engine.logging`. Never write `import logging` expecting our module, and never do relative `from . import logging` in a way that hides the standard library inside that file (1.4.5 imports the standard library as `stdlib_logging`).

### 1.4.4 `src/nument_engine/settings.py` (full file)
```python
"""Environment settings for the engine (A.12.7). One object, loaded once per process."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENGINE_DIR = Path(__file__).resolve().parents[2]   # .../nument-leads/engine
REPO_DIR = ENGINE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "prod"] = "dev"

    # Supabase
    database_url: SecretStr
    supabase_url: str = ""
    supabase_service_role_key: SecretStr | None = None

    # AI
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # Google
    google_maps_api_key: SecretStr | None = None
    google_service_account_json: SecretStr | None = None
    google_service_account_file: Path | None = None

    # Sheets
    sheet_master_id: str = ""
    sheet_caller_id: str = ""
    sheet_staging_id: str = ""

    # Behaviour
    associate_name: str = "Aditya"
    user_agent: str = "NumentLeadBot/1.0 (+https://nument.in)"
    alert_email: str | None = None
    backup_passphrase: SecretStr | None = None

    # Paths (not from env)
    segments_dir: Path = ENGINE_DIR / "segments"
    config_dir: Path = ENGINE_DIR / "config"
    prompts_dir: Path = ENGINE_DIR / "prompts"
    cache_dir: Path = ENGINE_DIR / ".cache"

    @model_validator(mode="after")
    def _safety(self) -> Settings:
        # Dev must never hold live sheet ids: protects the founder's real sheets.
        if self.app_env == "dev" and (self.sheet_master_id or self.sheet_caller_id):
            raise ValueError("APP_ENV=dev must not set SHEET_MASTER_ID or SHEET_CALLER_ID (use SHEET_STAGING_ID)")
        if self.app_env == "prod" and not (self.sheet_master_id and self.sheet_caller_id):
            raise ValueError("APP_ENV=prod needs SHEET_MASTER_ID and SHEET_CALLER_ID")
        return self

    def service_account_info(self) -> dict[str, Any]:
        """Google service account as a dict: JSON text from env (CI) or a file (local)."""
        if self.google_service_account_json:
            return json.loads(self.google_service_account_json.get_secret_value())
        if self.google_service_account_file:
            return json.loads(self.google_service_account_file.expanduser().read_text())
        raise RuntimeError("Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE")

    def target_sheets(self) -> dict[str, str]:
        """Which sheets this environment writes. Dev writes only the staging sheet."""
        if self.app_env == "prod":
            return {"master": self.sheet_master_id, "caller": self.sheet_caller_id}
        return {"master": self.sheet_staging_id}


@lru_cache
def get_settings() -> Settings:
    """Loads engine/.env.<APP_ENV> locally; in CI the variables already exist in the environment."""
    env = os.environ.get("APP_ENV", "dev")
    env_file = ENGINE_DIR / f".env.{env}"
    return Settings(_env_file=env_file if env_file.exists() else None)  # type: ignore[call-arg]
```

### 1.4.5 `src/nument_engine/logging.py` (full file)
```python
"""JSON logs with run id and run kind on every line (structlog)."""
from __future__ import annotations

import logging as stdlib_logging
import sys

import structlog


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    stdlib_logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(stdlib_logging, level))
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(stdlib_logging, level)),
        cache_logger_on_first_use=True,
    )


def bind_run(run_id: str, kind: str, env: str) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id, run_kind=kind, env=env)


def get_logger(name: str = "nlead") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

### 1.4.6 `src/nument_engine/db.py` (full skeleton)
```python
"""Postgres access through the Supabase session pooler (psycopg 3 + pool)."""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .settings import get_settings

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    """One small pool per process. GitHub Actions jobs are single process, so max 5 is plenty."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_settings().database_url.get_secret_value(),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "connect_timeout": 15, "application_name": "nlead"},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx() -> Iterator[Connection[Any]]:
    """A transaction: commits on success, rolls back on any exception."""
    with pool().connection() as conn, conn.transaction():
        yield conn


def fetch_all(query: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def fetch_one(query: str, params: Sequence[Any] | dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = fetch_all(query, params)
    return rows[0] if rows else None


def execute(query: str, params: Sequence[Any] | dict[str, Any] | None = None) -> int:
    with tx() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.rowcount


def upsert(table: str, rows: Iterable[dict[str, Any]], conflict: Sequence[str], update: Sequence[str] | None = None,
           returning: str | None = None) -> list[dict[str, Any]]:
    """INSERT ... ON CONFLICT (conflict) DO UPDATE SET col = EXCLUDED.col for each update column.
    dict and list values are wrapped as JSONB automatically. Returns RETURNING rows if asked."""
    rows = list(rows)
    if not rows:
        return []
    cols = list(rows[0].keys())
    update = list(update) if update is not None else [c for c in cols if c not in conflict]
    q = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) ON CONFLICT ({k}) {action}{ret}").format(
        t=sql.Identifier(table),
        c=sql.SQL(", ").join(map(sql.Identifier, cols)),
        v=sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        k=sql.SQL(", ").join(map(sql.Identifier, conflict)),
        action=(sql.SQL("DO UPDATE SET ") + sql.SQL(", ").join(
            sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in update)) if update else sql.SQL("DO NOTHING"),
        ret=sql.SQL(" RETURNING ") + sql.SQL(returning) if returning else sql.SQL(""),
    )
    out: list[dict[str, Any]] = []
    with tx() as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(q, [Jsonb(r[c]) if isinstance(r[c], (dict, list)) else r[c] for c in cols])
            if returning:
                out.extend(cur.fetchall())
    return out


def get_setting(key: str, default: Any = None) -> Any:
    row = fetch_one("select value from settings where key = %s", [key])
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    execute("insert into settings(key, value) values (%s, %s) "
            "on conflict (key) do update set value = excluded.value", [key, Jsonb(value)])
```
Pitfall: `upsert` runs one statement per row inside one transaction. That is fine up to a few thousand rows. For bigger loads (the first Overture import), Step 6 uses `COPY` into a temp table and one `INSERT ... SELECT ... ON CONFLICT`.

### 1.4.7 Run context: `src/nument_engine/pipeline/runs.py` (skeleton)
Every command runs inside a run context so that the `runs` table, logs and costs share one `run_id`.
```python
"""Run bookkeeping: one row in `runs` per execution, plus orchestration of night/morning runs (filled in Step 14)."""
from __future__ import annotations

import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .. import db
from ..logging import bind_run, get_logger

log = get_logger()


@dataclass
class Options:
    env: str = "dev"
    segments: list[str] = field(default_factory=list)   # empty = all enabled segments
    limit: int | None = None
    dry_run: bool = False


@dataclass
class RunContext:
    run_id: str
    kind: str
    opts: Options
    started_at: datetime
    stats: dict[str, Any] = field(default_factory=dict)
    failed_stages: list[str] = field(default_factory=list)

    def add(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n


@contextmanager
def run_context(kind: str, opts: Options) -> Iterator[RunContext]:
    run_id = str(uuid.uuid4())
    bind_run(run_id, kind, opts.env)
    rc = RunContext(run_id=run_id, kind=kind, opts=opts, started_at=datetime.now(UTC))
    db.execute("insert into runs(id, kind, started_at, status, stats) values (%s, %s, %s, 'running', %s)",
               [run_id, kind, rc.started_at, db.Jsonb({"dry_run": opts.dry_run, "limit": opts.limit,
                                                      "segments": opts.segments})])
    log.info("run.start", limit=opts.limit, dry_run=opts.dry_run, segments=opts.segments)
    try:
        yield rc
    except Exception as exc:
        db.execute("update runs set status='failed', finished_at=now(), stats=%s, error=%s where id=%s",
                   [db.Jsonb(rc.stats), "".join(traceback.format_exception(exc))[-4000:], run_id])
        log.error("run.failed", error=str(exc))
        raise
    else:
        status = "partial" if rc.failed_stages else "ok"
        db.execute("update runs set status=%s, finished_at=now(), stats=%s where id=%s",
                   [status, db.Jsonb({**rc.stats, "failed_stages": rc.failed_stages}), run_id])
        log.info("run.finish", status=status, **rc.stats)


def night(rc: RunContext) -> None:
    raise NotImplementedError("Built in Step 14")


def morning(rc: RunContext) -> None:
    raise NotImplementedError("Built in Step 14")
```
Note: `db.Jsonb` is re-exported by `db.py` (it imports `Jsonb`), so `db.Jsonb(...)` works.

### 1.4.8 Stub every pipeline module
Each module from 1.4.3 gets a `run` function with this exact shape, so the CLI can call it today and the real code lands in its step later. Example for `pipeline/universe.py`:
```python
"""Universe builder (Step 6)."""
from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, monthly: bool = False) -> dict[str, Any]:
    raise NotImplementedError("Built in Step 6")
```
Create the same stub (with the right step number in the message) for: `pipeline/signals.py` (Step 7), `pipeline/prefilter.py` (Step 8), `pipeline/research.py` (Step 9), `pipeline/extract.py` with `submit(rc)` and `collect(rc)` (Step 9), `pipeline/verify.py` (Step 10), `pipeline/score.py` (Step 11), `pipeline/judge.py` (Step 11), `pipeline/message.py` (Step 12), `sheet/push.py` and `sheet/pull.py` (Step 13), `learn/reweight.py` with `run` (Step 16), `learn/report.py` with `weekly(rc)` (Step 16), `learn/metrics.py` with `audit(rc)` (Step 17), `ops/health.py` (Step 22), `ops/backup.py` (Step 2), `ops/migrate_legacy.py` (Step 20). `evals/run_eval.py` gets `run(rc, subset: int | None)` (Step 17).

### 1.4.9 `src/nument_engine/cli.py` (full skeleton: every A.12.6 command)
```python
"""`nlead` command line. Global flags: --env, --segment (repeatable), --limit, --dry-run."""
from __future__ import annotations

import os
from typing import Annotated

import typer

from .logging import get_logger, setup_logging
from .pipeline.runs import Options, run_context

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Nument Leads engine")
extract_app = typer.Typer(no_args_is_help=True, help="AI fact extraction batches")
sheet_app = typer.Typer(no_args_is_help=True, help="Google Sheet sync")
report_app = typer.Typer(no_args_is_help=True, help="Reports")
run_app = typer.Typer(no_args_is_help=True, help="Orchestrated runs (GitHub Actions)")
app.add_typer(extract_app, name="extract")
app.add_typer(sheet_app, name="sheet")
app.add_typer(report_app, name="report")
app.add_typer(run_app, name="run")
log = get_logger()


@app.callback()
def main(
    ctx: typer.Context,
    env: Annotated[str, typer.Option("--env", help="dev or prod")] = "dev",
    segment: Annotated[list[str] | None, typer.Option("--segment", help="Segment id, repeatable")] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Max items per stage")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="No sheet writes, no batch submission")] = False,
    json_logs: Annotated[bool, typer.Option("--json-logs/--pretty-logs")] = True,
) -> None:
    if env not in ("dev", "prod"):
        raise typer.BadParameter("--env must be dev or prod")
    os.environ["APP_ENV"] = env          # must happen before settings load
    from .settings import get_settings
    get_settings.cache_clear()
    get_settings()                        # fail fast on bad env files
    setup_logging(json_output=json_logs)
    ctx.obj = Options(env=env, segments=segment or [], limit=limit, dry_run=dry_run)


def _opts(ctx: typer.Context) -> Options:
    return ctx.obj  # type: ignore[no-any-return]


@app.command()
def universe(ctx: typer.Context, monthly: bool = typer.Option(False, "--monthly")) -> None:
    from .pipeline import universe as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc, monthly=monthly)


@app.command()
def signals(ctx: typer.Context) -> None:
    from .pipeline import signals as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command()
def prefilter(ctx: typer.Context) -> None:
    from .pipeline import prefilter as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command()
def research(ctx: typer.Context) -> None:
    from .pipeline import research as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@extract_app.command("submit")
def extract_submit(ctx: typer.Context) -> None:
    from .pipeline import extract as m
    with run_context("manual", _opts(ctx)) as rc:
        m.submit(rc)


@extract_app.command("collect")
def extract_collect(ctx: typer.Context) -> None:
    from .pipeline import extract as m
    with run_context("manual", _opts(ctx)) as rc:
        m.collect(rc)


@app.command()
def verify(ctx: typer.Context) -> None:
    from .pipeline import verify as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command()
def score(ctx: typer.Context) -> None:
    from .pipeline import score as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command()
def judge(ctx: typer.Context) -> None:
    from .pipeline import judge as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command()
def message(ctx: typer.Context) -> None:
    from .pipeline import message as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@sheet_app.command("push")
def sheet_push(ctx: typer.Context) -> None:
    from .sheet import push as m
    with run_context("sheet_sync", _opts(ctx)) as rc:
        m.run(rc)


@sheet_app.command("pull")
def sheet_pull(ctx: typer.Context) -> None:
    from .sheet import pull as m
    with run_context("sheet_sync", _opts(ctx)) as rc:
        m.run(rc)


@sheet_app.command("sync")
def sheet_sync(ctx: typer.Context) -> None:
    from .sheet import pull, push
    with run_context("sheet_sync", _opts(ctx)) as rc:
        pull.run(rc)          # always pull people's edits first
        push.run(rc)


@app.command()
def learn(ctx: typer.Context) -> None:
    from .learn import reweight as m
    with run_context("weekly", _opts(ctx)) as rc:
        m.run(rc)


@report_app.command("weekly")
def report_weekly(ctx: typer.Context) -> None:
    from .learn import report as m
    with run_context("weekly", _opts(ctx)) as rc:
        m.weekly(rc)


@app.command()
def audit(ctx: typer.Context) -> None:
    from .learn import metrics as m
    with run_context("weekly", _opts(ctx)) as rc:
        m.audit(rc)


@app.command(name="eval")
def eval_(ctx: typer.Context, subset: int | None = typer.Option(None, "--subset")) -> None:
    from evals import run_eval as m   # engine/evals is on the path when run from engine/
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc, subset=subset)


@app.command()
def health(ctx: typer.Context) -> None:
    from .ops import health as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command()
def backup(ctx: typer.Context) -> None:
    from .ops import backup as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@app.command(name="migrate-legacy")
def migrate_legacy(ctx: typer.Context) -> None:
    from .ops import migrate_legacy as m
    with run_context("manual", _opts(ctx)) as rc:
        m.run(rc)


@run_app.command("night")
def run_night(ctx: typer.Context) -> None:
    from .pipeline import runs
    with run_context("night", _opts(ctx)) as rc:
        runs.night(rc)


@run_app.command("morning")
def run_morning(ctx: typer.Context) -> None:
    from .pipeline import runs
    with run_context("morning", _opts(ctx)) as rc:
        runs.morning(rc)


@run_app.command("sheet")
def run_sheet(ctx: typer.Context) -> None:
    sheet_sync(ctx)


@run_app.command("weekly")
def run_weekly(ctx: typer.Context) -> None:
    from .learn import metrics, report, reweight
    with run_context("weekly", _opts(ctx)) as rc:
        reweight.run(rc)
        report.weekly(rc)
        metrics.audit(rc)


@run_app.command("monthly")
def run_monthly(ctx: typer.Context) -> None:
    from .pipeline import universe as m
    with run_context("monthly", _opts(ctx)) as rc:
        m.run(rc, monthly=True)


if __name__ == "__main__":
    app()
```
Notes:
- Imports inside each command keep `nlead --help` fast and let unbuilt modules exist as stubs.
- `run_context` writes a `runs` row, so commands need the database. Until Step 2 creates the `runs` table, test only `--help` (1.4.11).

### 1.4.10 First tests: `engine/tests/test_cli.py`
```python
from typer.testing import CliRunner

from nument_engine.cli import app

runner = CliRunner()


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["universe", "signals", "prefilter", "research", "extract", "verify", "score", "judge",
                 "message", "sheet", "learn", "report", "audit", "eval", "health", "backup", "migrate-legacy", "run"]:
        assert name in result.stdout


def test_dev_refuses_live_sheet_ids(monkeypatch) -> None:
    import pytest
    from pydantic import ValidationError

    from nument_engine.settings import Settings
    with pytest.raises(ValidationError):
        Settings(app_env="dev", database_url="postgresql://x", sheet_master_id="LIVE")  # type: ignore[arg-type]
```

### 1.4.11 Check the engine skeleton
```bash
cd ~/Desktop/nument-leads/engine
uv run nlead --help
uv run nlead run --help
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -m "not live" -q
```
All must pass. `nlead universe` will fail with "relation runs does not exist" until Step 2. That is expected.

## 1.5 Web app skeleton (Next.js)

### 1.5.1 Create the app
```bash
cd ~/Desktop/nument-leads
pnpm create next-app@latest web --typescript --tailwind --eslint --app --src-dir \
  --import-alias "@/*" --use-pnpm --yes
```
Flags change between Next.js versions (verify at build with `pnpm create next-app@latest --help`). The result must be: TypeScript, Tailwind, ESLint, App Router, `src/` folder, `@/*` alias.

### 1.5.2 Dependencies
```bash
cd web
pnpm add @supabase/ssr @supabase/supabase-js @tanstack/react-table @dnd-kit/core @dnd-kit/sortable \
  react-hook-form zod @hookform/resolvers recharts date-fns date-fns-tz lucide-react clsx tailwind-merge
pnpm add -D vitest @vitejs/plugin-react jsdom @testing-library/react @playwright/test
pnpm exec playwright install chromium
```
Add the package manager field so CI uses the same pnpm (version from `pnpm -v`):
```json
"packageManager": "pnpm@11.5.1"
```

### 1.5.3 Folder structure
```bash
cd ~/Desktop/nument-leads/web/src
mkdir -p "app/(auth)/login" "app/(auth)/reset-password" "app/(app)/leads/[id]" "app/(app)/pipeline" \
  "app/(app)/insights" "app/(app)/engine" "app/(app)/inbox" "app/(app)/settings" app/api/health \
  components/ui components/layout components/leads lib/supabase lib/queries styles
```
Route meaning (contents are built in Step 15):
| Route | Page |
|---|---|
| `/login`, `/reset-password` | Email + password login and reset |
| `/` (inside the `(app)` group) | Today |
| `/leads`, `/leads/[id]` | Leads list, lead page |
| `/pipeline` | Stage board |
| `/insights` | Results by segment and signal |
| `/engine` | Engine control (admin) |
| `/inbox` | Pasted public posts (admin) |
| `/settings` | Users, suppression list, profile |

Move the starter page: `create-next-app` writes `src/app/page.tsx`. Move it into the group so `/` is the Today page:
```bash
mv app/page.tsx "app/(app)/page.tsx"
```
Replace each new page with a placeholder, for example `src/app/(app)/leads/page.tsx`:
```tsx
export default function Page() {
  return <main className="p-8 font-sans">Leads: built in Step 15.</main>;
}
```

### 1.5.4 Nument kit tokens
```bash
cp ~/Desktop/Extra/sarvam-design-kit/tokens/tokens.css ~/Desktop/nument-leads/web/src/styles/tokens.css
```
Then edit `web/src/styles/tokens.css`:
1. **Delete** the `@import url("https://fonts.googleapis.com/...")` line near the top. `next/font` loads the fonts (faster, no layout shift, no double download).
2. Keep everything else (colours, radii, shadows, type scale) unchanged. Do not invent new colours: the founder wants the app faithful to the kit.

### 1.5.5 Fonts with `next/font` (full `src/app/layout.tsx`)
```tsx
import type { Metadata } from "next";
import { DM_Mono, Figtree, Newsreader } from "next/font/google";
import "@/styles/tokens.css";
import "./globals.css";

const newsreader = Newsreader({ subsets: ["latin"], variable: "--nf-newsreader", display: "swap" });
const figtree = Figtree({ subsets: ["latin"], variable: "--nf-figtree", display: "swap" });
const dmMono = DM_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--nf-dmmono", display: "swap" });

export const metadata: Metadata = {
  title: "Nument Leads",
  robots: { index: false, follow: false },   // private tool: never indexed
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${newsreader.variable} ${figtree.variable} ${dmMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

### 1.5.6 Map kit fonts and colours into Tailwind
If `create-next-app` produced **Tailwind v4** (CSS-first, no `tailwind.config.ts`), put this at the top of `src/app/globals.css` (verify at build which version you got):
```css
@import "tailwindcss";

/* next/font variables feed the kit's font tokens */
:root {
  --font-display: var(--nf-newsreader), Georgia, serif;
  --font-sans: var(--nf-figtree), system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: var(--nf-dmmono), ui-monospace, Menlo, monospace;
}

@theme inline {
  --font-display: var(--font-display);
  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);
  --color-ink: var(--color-ink);
  --color-tx: var(--color-tx);
  --color-tx-secondary: var(--color-tx-secondary);
  --color-tx-tertiary: var(--color-tx-tertiary);
  --color-bg: var(--color-bg);
  --color-st: var(--color-st);
  --color-indigo-100: var(--indigo-100);
  --color-indigo-200: var(--indigo-200);
  --color-indigo-600: var(--indigo-600);
  --color-indigo-800: var(--indigo-800);
}

body {
  font-family: var(--font-sans);
  background: var(--color-bg);
  color: var(--color-tx);
}
```
If it produced **Tailwind v3**, put the same mappings in `tailwind.config.ts` under `theme.extend.fontFamily` and `theme.extend.colors` (that is the `tailwind.config.ts` listed in A.8; with v4 that file is not needed).

### 1.5.7 Health route: `src/app/api/health/route.ts`
Render uses it as the health check (Step 15).
```ts
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ ok: true, app: "nument-leads-web", time: new Date().toISOString() });
}
```

### 1.5.8 Scripts in `web/package.json`
```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start -p ${PORT:-3000}",
  "lint": "next lint",
  "test": "vitest",
  "e2e": "playwright test"
}
```
If your Next.js version removed `next lint` (verify at build), use `"lint": "eslint ."` instead.

Minimal `web/vitest.config.ts` so `pnpm test --run` passes with zero tests:
```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", passWithNoTests: true, exclude: ["tests/**", "node_modules/**"] },
});
```

### 1.5.9 Check the web skeleton
```bash
cd ~/Desktop/nument-leads/web
pnpm dev            # open http://localhost:3000, page renders in Figtree
pnpm lint && pnpm test --run && pnpm build
```

## 1.6 Supabase folder
```bash
cd ~/Desktop/nument-leads
npx supabase@latest init          # creates supabase/config.toml
npx supabase@latest login         # opens the browser, founder or builder signs in
npx supabase@latest link --project-ref <DEV_PROJECT_REF>   # asks for the dev DB password
mkdir -p supabase/migrations supabase/tests
```
The project ref is the `<ref>` part of `https://<ref>.supabase.co`. Migrations are written in Step 2. Always link to **dev** while building; Step 21 pushes to prod.

## 1.7 CI skeleton

### 1.7.1 `.github/workflows/ci.yml` (full file)
```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  engine:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: engine
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6          # major version: verify at build
        with:
          enable-cache: true
      - run: uv python install 3.12
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy src
      - run: uv run pytest -m "not live" -q
        env:
          APP_ENV: dev
          DATABASE_URL: postgresql://ci:ci@localhost:5432/ci   # unit tests never connect

  web:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4           # reads packageManager from web/package.json
        with:
          package_json_file: web/package.json
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: web/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm test --run
      - run: pnpm build
        env:
          NEXT_PUBLIC_SUPABASE_URL: https://example.supabase.co
          NEXT_PUBLIC_SUPABASE_ANON_KEY: ci-placeholder
```
Step 17 extends this file with the golden-set eval job.

### 1.7.2 `.github/dependabot.yml`
```yaml
version: 2
updates:
  - package-ecosystem: "uv"            # uv support in Dependabot: verify at build; fall back to "pip" if missing
    directory: "/engine"
    schedule: { interval: "monthly" }
    open-pull-requests-limit: 5
  - package-ecosystem: "npm"
    directory: "/web"
    schedule: { interval: "monthly" }
    open-pull-requests-limit: 5
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "monthly" }
```

## 1.8 First commit and push
```bash
cd ~/Desktop/nument-leads
git add .
git status          # read the list: no .env files, no service-account JSON, no node_modules, no .venv
gitleaks git --staged --redact   # optional, see 1.3.6
git commit -m "Step 1: project skeleton (engine, web, supabase, CI)"
git push -u origin main
```
Open the repo's **Actions** tab and wait for the `ci` workflow: both jobs must be green.

## 1.9 Pitfalls
| Problem | Cause | Fix |
|---|---|---|
| `uv sync` picks Python 3.14 | System Python is 3.14 on this Mac | `uv python pin 3.12` and `requires-python = ">=3.12,<3.13"` (done above) |
| `duckdb` or `pyarrow` wheel build fails | Python version too new | Stay on 3.12 |
| `psycopg` errors about prepared statements | Using the transaction pooler (6543) | Use the session pooler on port 5432 |
| CI cannot reach the database | Direct connection is IPv6 only | Session pooler URI, never `db.<ref>.supabase.co` |
| `pnpm install --frozen-lockfile` fails in CI | Lockfile not committed or pnpm version differs | Commit `web/pnpm-lock.yaml`; set `packageManager` |
| Fonts look like Times/Arial | `tokens.css` still has the Google Fonts import, or the `--nf-*` variables are not on `<html>` | 1.5.4 step 1 and 1.5.5 |
| `nlead` commands fail with "relation runs does not exist" | Step 2 not done | Expected until Step 2 |
| A `.env` file shows in `git status` | Wrong file name | Only `.env.example` may be committed; fix `.gitignore` before committing |

## 1.10 Done when
- [ ] `~/Desktop/nument-leads` is a git repo with `origin` set to `with-nument/nument-lead`.
- [ ] Root files exist: `.gitignore`, `.editorconfig`, `.env.example`, `README.md`, `docs/` placeholders.
- [ ] `engine/.env.dev`, `engine/.env.prod`, `web/.env.local` exist locally with permission 600 and are ignored by git.
- [ ] `uv run nlead --help` lists every command from A.12.6, and `uv run nlead run --help` lists night, morning, sheet, weekly, monthly.
- [ ] `ruff`, `mypy` and `pytest -m "not live"` pass in `engine/`.
- [ ] Settings refuse live sheet IDs when `APP_ENV=dev` (test passes).
- [ ] `pnpm dev` renders a page in the kit fonts; `pnpm lint`, `pnpm test --run`, `pnpm build` pass.
- [ ] `supabase/config.toml` exists and the CLI is linked to the dev project.
- [ ] The first push made the `ci` workflow run green for both jobs.
- [ ] No secret was committed (checked with `git status` and, ideally, `gitleaks`).

---

# Step 2: Database (Supabase Postgres)

## 2.1 Goal and outputs

**Goal:** one Postgres database that is the single source of truth: businesses, signals, facts, scores, leads, stages, costs and runs. The engine writes with the service role. The web app reads and edits as a logged-in user, protected by Row Level Security (RLS). The sheets are synced from it (Step 13).

**You need first:**
- Step 0: both Supabase projects, their keys and auth settings (0.3), and where each secret lives (0.10).
- Step 1: the repo, the `supabase/` folder linked to the **dev** project (1.6), and `engine/src/nument_engine/db.py` (1.4.6).

**Outputs of this step:**

| Output | Path |
|---|---|
| Core schema | `supabase/migrations/0001_core.sql` |
| Views and helper functions | `supabase/migrations/0002_views.sql` |
| Row Level Security, grants, storage buckets | `supabase/migrations/0003_rls.sql` |
| Seed data | `supabase/migrations/0004_seed.sql` |
| RLS and trigger tests | `supabase/tests/rls_test.sql` and `engine/tests/test_rls.py` |
| A small change to `db.tx()` | `engine/src/nument_engine/db.py` |

In this step you push to **dev only**. Step 21 pushes the same migrations to prod.

---

## 2.2 Check the Supabase projects (made in Step 0)

Step 0 already created both projects. Before writing SQL, check each item:

| # | Check | Where it was set |
|---|---|---|
| 1 | `nument-leads-dev` and `nument-leads-prod` exist in South Asia (Mumbai), Free plan | 0.3.2, 0.3.3 |
| 2 | Sign-ups off, confirm email on, minimum password length 12, Site URL and redirect URLs set | 0.3.7 |
| 3 | `DATABASE_URL` is the **session pooler** string (port 5432) for each project | 0.3.5 |
| 4 | Keys are stored as in table 0.10: `engine/.env.dev`, `engine/.env.prod`, `web/.env.local`, GitHub environments `dev` and `prod` | 0.3.6, 0.10 |
| 5 | The dev project is paired only with the **Leads-staging** sheet (`SHEET_STAGING_ID`). Prod is paired with the real master and caller sheets (Step 13). Never point dev at the real sheets | 0.5, Step 13 |
| 6 | Data API settings (verify at build where the dashboard shows them): the `public` schema is exposed. Migration 0003 removes default access for anything created later, so a dashboard switch like "expose new tables automatically" does not matter | this step |

> The Google service account key (`~/.config/nument-leads/service-account.json`) and every API key are **not** database data. Never store a key in any table, including `settings`.

---

## 2.3 Connections

| Who | How | RLS? |
|---|---|---|
| Engine (laptop and GitHub Actions) | `DATABASE_URL`, session pooler, port 5432, IPv4, user `postgres` | **Bypassed.** Only `engine/.env.dev`, `engine/.env.prod`, GitHub environment secrets (`dev`, `prod`) and Render server variables hold it |
| Web app, browser and server | supabase-js over HTTPS with the anon key and the user's session | **Applies** |
| Web app, admin server actions | supabase-js with `SUPABASE_SERVICE_ROLE_KEY`, server code only, after a role check (Step 15) | Bypassed |

Not used: the direct connection (IPv6 only on the free plan, so it fails on GitHub runners) and the transaction pooler on port 6543 (breaks session settings).

### 2.3.1 Change `db.tx()` so triggers know who is writing
The lead triggers in 2.6 log activities. They read two transaction settings to label them: `app.source` (`engine` or `sheet`) and `app.context` (extra payload keys, for example `{"sheet": "master"}`). Replace `tx()` in `engine/src/nument_engine/db.py` (Step 1.4.6) with this version and add `import json` to the imports:

```python
@contextmanager
def tx(source: str = "engine", context: dict[str, Any] | None = None) -> Iterator[Connection[Any]]:
    """A transaction: commits on success, rolls back on any exception.

    source   'engine' or 'sheet'. Becomes activities.source when a lead trigger logs something.
    context  Extra keys merged into the activity payload, for example {"sheet": "master"}.
    """
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            "select set_config('app.source', %s, true), set_config('app.context', %s, true)",
            (source, json.dumps(context or {})),
        )
        yield conn
```

Step 13 opens its write transactions with `db.tx(source="sheet", context={"sheet": target})`. Everything else keeps the default.

### 2.3.2 Rules
- Store every timestamp as `timestamptz` (UTC). Convert to IST only for display and for "today": `(now() at time zone 'Asia/Kolkata')::date`.
- `SUPABASE_SERVICE_ROLE_KEY` never goes into a `NEXT_PUBLIC_` variable or browser code. It bypasses everything in this step.

---

## 2.4 Extensions

Supabase installs extensions into the `extensions` schema, which is on the default search path (verify at build).

| Extension | Why |
|---|---|
| `pgcrypto` | `digest()` for hashes (`gen_random_uuid()` is built into Postgres 13 and later) |
| `pg_trgm` | Fuzzy name matching for dedupe (Step 6): `similarity()` and a trigram index |
| `unaccent` | Accent-free name normalisation for dedupe (Step 6) |

All three are created at the top of `0001_core.sql`.

---

## 2.5 Schema design rules
1. Primary keys are `uuid default gen_random_uuid()`, except `settings`, `segments` and `source_health` (natural text keys), `llm_cache` (text key), `llm_batch_reservations` (bigserial) and `sheet_snapshots` (composite key).
2. Timestamps are `timestamptz not null default now()` unless they can be empty.
3. Enumerations are `text` with a named or column `check`, not Postgres enum types (easier to change).
4. Flexible data is `jsonb not null default '{}'::jsonb`.
5. `updated_at` is kept right by one trigger function, `set_updated_at()`.
6. Businesses are not deleted in normal work; they change `status`. The only deletion path is a "forget me" request (Step 18.2.3).
7. RLS is on for every table (0003). The `anon` role gets nothing.
8. Money lives only in `leads.deal_value_inr`. App users never read it from `leads`. Admins read it through `v_leads_admin`. It is written only by admin server actions with the service role (Step 15).
9. **Triggers own four activity types:** `lead_created`, `stage_change`, `grade_change`, `message_edited`. Code never inserts these four, or the timeline gets duplicates. Code logs every other type.
10. **Nothing new is exposed by default.** After 0003, a new table or view is invisible to app users until its migration grants access on purpose (2.8.4).

---

## 2.6 Migration 0001: core schema

Create `supabase/migrations/0001_core.sql` with exactly this content.

```sql
-- 0001_core.sql : core schema for nument-leads
-- Apply with: npx supabase db push (dev in Step 2, prod in Step 21)

create extension if not exists pgcrypto with schema extensions;
create extension if not exists pg_trgm  with schema extensions;
create extension if not exists unaccent with schema extensions;

-- =========================================================================
-- Helper
-- =========================================================================
create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- =========================================================================
-- settings: key/value configuration read by engine and app (keys in 0004)
-- =========================================================================
create table public.settings (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
create trigger settings_updated_at before update on public.settings
  for each row execute function public.set_updated_at();

-- =========================================================================
-- segments: one row per domain x country; config is a copy of the YAML (Step 3)
-- =========================================================================
create table public.segments (
  id             text primary key check (id ~ '^[a-z0-9]+-[a-z]{2}$'),
  domain         text not null check (domain in
                   ('clinics','realestate','education','d2c','hospitality',
                    'auto','finance','wellness','firms')),
  country        char(2) not null check (country ~ '^[a-z]{2}$'),
  display_name   text not null,
  enabled        boolean not null default false,
  daily_quota    integer not null default 0 check (daily_quota >= 0),
  config         jsonb not null default '{}'::jsonb,
  config_version text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint segments_id_matches check (id = domain || '-' || country)
);
create trigger segments_updated_at before update on public.segments
  for each row execute function public.set_updated_at();

-- =========================================================================
-- businesses: one real company after dedupe (Step 6)
-- =========================================================================
create table public.businesses (
  id                uuid primary key default gen_random_uuid(),
  segment_id        text not null references public.segments(id)
                      on update cascade on delete restrict,
  name              text not null,
  norm_name         text not null,
  website           text,
  web_domain        text,
  country           char(2) not null,
  city              text,
  locality          text,
  address           text,
  lat               double precision check (lat between -90 and 90),
  lng               double precision check (lng between -180 and 180),
  category          text,                 -- raw source category (Overture code or Places type)
  subcategory       text,                 -- our class: a ticket_class key of the segment (Step 3)
  place_id          text,
  overture_id       text,
  branches_count    integer check (branches_count >= 0),
  staff_count       integer check (staff_count >= 0),
  review_count      integer check (review_count >= 0),            -- Places content: 30 days max (A.4.4)
  rating            numeric(2,1) check (rating between 0 and 5),   -- Places content: 30 days max
  places_fetched_at timestamptz,
  status            text not null default 'candidate' check (status in
                      ('candidate','queued','researched','qualified',
                       'rejected','suppressed','dormant')),
  reject_reason     text,
  queued_at         timestamptz,          -- set by the pre-filter (Step 8)
  queue_priority    real,                 -- higher is researched first (Step 8.7)
  extra             jsonb not null default '{}'::jsonb,   -- small extras (registry ids and similar)
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now(),
  researched_at     timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create unique index businesses_place_id_uq    on public.businesses (place_id)    where place_id is not null;
create unique index businesses_overture_id_uq on public.businesses (overture_id) where overture_id is not null;
create unique index businesses_seg_domain_uq  on public.businesses (segment_id, web_domain) where web_domain is not null;
create index businesses_seg_status_idx        on public.businesses (segment_id, status);
create index businesses_seg_city_idx          on public.businesses (segment_id, city);
create index businesses_queue_idx             on public.businesses (queue_priority desc) where status = 'queued';
create index businesses_norm_name_trgm        on public.businesses using gin (norm_name extensions.gin_trgm_ops);
create trigger businesses_updated_at before update on public.businesses
  for each row execute function public.set_updated_at();

-- =========================================================================
-- source_records: raw records from each source, linked to a business
-- =========================================================================
create table public.source_records (
  id          uuid primary key default gen_random_uuid(),
  source      text not null,
  source_key  text not null,              -- the id inside that source
  business_id uuid references public.businesses(id) on delete set null,
  payload     jsonb not null default '{}'::jsonb,   -- keep slim: only fields we use
  fetched_at  timestamptz not null default now(),
  constraint source_records_uq unique (source, source_key),
  -- A new registry adapter adds its key here in a new migration on the day it goes live (2.6.1).
  -- legacy and legacy_skip are written once by `nlead migrate-legacy` (Step 20).
  constraint source_records_source_known check (source in
    ('overture','places','art_registry','osm','apna','grounded_search',
     'gdelt','careers_watch','adzuna','practo','legacy','legacy_skip'))
);
create index source_records_business_idx on public.source_records (business_id);

-- =========================================================================
-- signals: dated evidence of need (A.12.3)
-- =========================================================================
create table public.signals (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  type        text not null check (type in
                ('public_ask','tender','hiring_builder','hiring_frontdesk',
                 'review_pain','ads_running','no_booking','slow_site',
                 'new_place','new_branch','news','funding')),
  category    text not null check (category in ('stated_need','visible_pain','growth','money')),
  points      numeric(5,2) not null default 0,   -- effective points (segment override applied, Step 7)
  observed_at timestamptz not null,
  expires_at  timestamptz not null,
  source      text not null,                     -- watcher name, or 'manual' for ads_running from the app
  url         text,
  quote       text,
  details     jsonb not null default '{}'::jsonb,
  dedupe_key  text not null unique,              -- for example 'apna:job:123456'
  created_at  timestamptz not null default now(),
  constraint signals_expiry_after_observed check (expires_at > observed_at)
);
create index signals_business_active_idx on public.signals (business_id, expires_at);
create index signals_type_idx on public.signals (type, observed_at desc);

-- =========================================================================
-- pages: fetched web pages (retention in Step 18.2.2)
-- =========================================================================
create table public.pages (
  id             uuid primary key default gen_random_uuid(),
  business_id    uuid references public.businesses(id) on delete cascade,
  url            text not null unique,
  fetched_at     timestamptz not null default now(),
  http_status    integer,
  render_mode    text not null default 'http' check (render_mode in ('http','browser')),
  title          text,
  text           text,                  -- cleaned main text, max 20,000 characters (Step 9)
  text_hash      text,                  -- sha256 of text, kept after text is deleted
  robots_allowed boolean not null default true
);
create index pages_business_idx on public.pages (business_id);
create index pages_fetched_idx  on public.pages (fetched_at);

-- =========================================================================
-- facts: extracted facts, each with quote and url, verified by code (Step 10)
-- =========================================================================
create table public.facts (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,
  field        text not null,           -- for example decision_maker, staff_or_doctors, price_point
  value        jsonb not null,
  quote        text,
  url          text,
  page_id      uuid references public.pages(id) on delete set null,
  model        text,                    -- model that extracted it, or 'rule'
  verified     boolean not null default false,
  verify_score numeric(5,2),            -- 0 to 100 match score; -1 = lost a conflict (Step 10)
  verified_at  timestamptz,
  created_at   timestamptz not null default now()
);
create index facts_business_field_idx on public.facts (business_id, field, created_at desc);

-- =========================================================================
-- contacts: phones, emails, decision makers
-- =========================================================================
create table public.contacts (
  id                uuid primary key default gen_random_uuid(),
  business_id       uuid not null references public.businesses(id) on delete cascade,
  name              text,
  role              text,
  phone_e164        text check (phone_e164 ~ '^\+[1-9][0-9]{6,14}$'),
  phone_type        text not null default 'unknown'
                      check (phone_type in ('mobile','landline','tollfree','unknown')),
  email             text,
  source            text not null check (source in ('website','google_listing','registry','other')),
  source_url        text,
  quote             text,
  is_decision_maker boolean not null default false,
  verified          boolean not null default false,
  verified_at       timestamptz,          -- the 30-day Google listing rule (Step 10)
  do_not_contact    boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint contacts_has_something check (phone_e164 is not null or email is not null or name is not null)
);
create unique index contacts_business_phone_uq on public.contacts (business_id, phone_e164) where phone_e164 is not null;
create unique index contacts_business_email_uq on public.contacts (business_id, lower(email)) where email is not null;
create index contacts_phone_idx on public.contacts (phone_e164);
create trigger contacts_updated_at before update on public.contacts
  for each row execute function public.set_updated_at();

-- =========================================================================
-- scores: every scoring run is kept
-- =========================================================================
create table public.scores (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  version     text not null,             -- SCORE_VERSION from score.py, for example 's1.0' (Step 11)
  fit         smallint not null check (fit between 0 and 3),
  can_pay     numeric(5,2) not null default 0 check (can_pay between 0 and 30),
  intent      numeric(5,2) not null default 0 check (intent between 0 and 40),
  reach       numeric(4,2) not null default 0 check (reach between 0 and 1),
  total       numeric(5,2) not null check (total between 0 and 100),
  grade       char(1) not null check (grade in ('A','B','C','D')),
  pitch_mode  text not null check (pitch_mode in ('stated_need','visible_pain','fit_only')),
  reasons     jsonb not null default '{}'::jsonb,
  judge_grade char(1) check (judge_grade in ('A','B','C','D')),
  judge_note  text,
  judge_model text,
  computed_at timestamptz not null default now()
);
create index scores_business_time_idx on public.scores (business_id, computed_at desc);

-- =========================================================================
-- profiles: app users and roles (one row per auth.users row)
-- =========================================================================
create table public.profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  full_name  text,
  role       text not null default 'viewer' check (role in ('admin','caller','viewer')),
  created_at timestamptz not null default now()
);

-- Every new auth user gets a 'viewer' profile. An admin then sets the role (Step 15).
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id, full_name, role)
  values (new.id,
          coalesce(new.raw_user_meta_data ->> 'full_name', split_part(new.email, '@', 1)),
          'viewer')
  on conflict (user_id) do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Role of the logged-in user ('none' when not logged in or no profile). Used by every policy.
create or replace function public.auth_role() returns text
language sql stable security definer set search_path = public as $$
  select coalesce((select role from public.profiles where user_id = auth.uid()), 'none')
$$;

-- =========================================================================
-- leads: graded businesses with a message and a stage
-- =========================================================================
create table public.leads (
  id                  uuid primary key default gen_random_uuid(),
  business_id         uuid not null references public.businesses(id) on delete restrict,
  segment_id          text not null references public.segments(id) on update cascade on delete restrict,
  score_id            uuid references public.scores(id) on delete set null,
  grade               char(1) not null check (grade in ('A','B','C','D')),
  pitch_mode          text not null check (pitch_mode in ('stated_need','visible_pain','fit_only')),
  test_group          text,              -- '{segment_id}:{pitch_mode}:{angle}' (A.12.4)
  angle               text,
  channel             text not null default 'whatsapp' check (channel in ('whatsapp','email','form')),
  message             text,              -- WhatsApp or contact-form text
  message_alt         text,
  email_subject       text,              -- only when channel = 'email' (Step 12)
  email_body          text,
  followup_d3         text,
  followup_d7         text,
  message_model       text,
  message_check_score numeric(4,1),      -- 0 to 10 from the critic (Step 12)
  stage               text not null default 'new' check (stage in
                        ('new','contacted','talking','discovery_booked','discovery_done',
                         'proposal_sent','won','retainer','lost','not_now','not_a_fit','wrong_contact')),
  owner_id            uuid references public.profiles(user_id) on delete set null,
  wa_at               date,              -- first message sent (IST date)
  call_at             date,
  d3_at               date,
  d7_at               date,
  meeting_at          timestamptz,
  next_step           text,
  due_at              date,
  skipped_until       timestamptz,       -- "Skip" in the app hides the lead from Today until then
  regen_requested_at  timestamptz,       -- the app asks the engine for a new message
  deal_value_inr      numeric(12,2) check (deal_value_inr >= 0),   -- money: see 2.8.3
  notes               text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  last_activity_at    timestamptz not null default now()
);
-- One open lead per business. Closed stages may repeat later (a new cycle).
create unique index leads_one_open_per_business on public.leads (business_id)
  where stage not in ('won','retainer','lost','not_now','not_a_fit','wrong_contact');
create index leads_stage_idx         on public.leads (stage);
create index leads_segment_grade_idx on public.leads (segment_id, grade);
create index leads_due_idx           on public.leads (due_at) where due_at is not null;
create index leads_regen_idx         on public.leads (regen_requested_at) where regen_requested_at is not null;

-- Keep updated_at and last_activity_at right, and fill the first-message date.
create or replace function public.leads_before_write() returns trigger
language plpgsql as $$
begin
  if tg_op = 'UPDATE' then
    new.updated_at := now();
    if new.stage is distinct from old.stage then
      new.last_activity_at := now();
    end if;
  end if;
  -- Marking Contacted without a date means "sent today" (the 17 Oct 2026 sheet bug).
  if new.stage = 'contacted' and new.wa_at is null then
    new.wa_at := (now() at time zone 'Asia/Kolkata')::date;
  end if;
  return new;
end $$;
create trigger leads_before_write before insert or update on public.leads
  for each row execute function public.leads_before_write();

-- =========================================================================
-- activities: the lead timeline (app, sheet and engine all write here)
-- =========================================================================
create table public.activities (
  id      uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  user_id uuid default auth.uid() references public.profiles(user_id) on delete set null,
  source  text not null check (source in ('app','sheet','engine')),
  type    text not null check (type in (
            -- written by the lead triggers only (rule 2.5.9)
            'lead_created','stage_change','grade_change','message_edited',
            -- written by code
            'message_flagged','regen_request','sent','followup_sent','reply','call','meeting',
            'proposal','proposal_upload','note','edit','feedback','skip','wrong_contact','undo',
            'merge','ai_output','conflict_overridden','unknown_stage')),
  at      timestamptz not null default now(),
  payload jsonb not null default '{}'::jsonb
);
create index activities_lead_time_idx on public.activities (lead_id, at desc);
create index activities_type_time_idx on public.activities (type, at desc);

-- Log creation, stage changes, grade changes and app edits of the message.
create or replace function public.leads_after_write() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_source text := coalesce(nullif(current_setting('app.source', true), ''),
                            case when auth.uid() is null then 'engine' else 'app' end);
  v_ctx    jsonb := coalesce(nullif(current_setting('app.context', true), '')::jsonb, '{}'::jsonb);
begin
  if tg_op = 'INSERT' then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'lead_created',
            jsonb_build_object('grade', new.grade, 'pitch_mode', new.pitch_mode,
                               'channel', new.channel, 'test_group', new.test_group) || v_ctx);
    return new;
  end if;
  if new.stage is distinct from old.stage then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'stage_change',
            jsonb_build_object('from', old.stage, 'to', new.stage) || v_ctx);
  end if;
  if new.grade is distinct from old.grade then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'grade_change',
            jsonb_build_object('from', old.grade, 'to', new.grade) || v_ctx);
  end if;
  if auth.uid() is not null and (new.message is distinct from old.message
                                 or new.message_alt is distinct from old.message_alt) then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'message_edited', v_ctx);
  end if;
  return new;
end $$;
create trigger leads_after_write after insert or update on public.leads
  for each row execute function public.leads_after_write();

-- =========================================================================
-- feedback: thumbs up or down on lead quality (Step 16)
-- =========================================================================
create table public.feedback (
  id      uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  user_id uuid default auth.uid() references public.profiles(user_id) on delete set null,
  rating  smallint not null check (rating in (-1, 1)),
  reason  text,
  at      timestamptz not null default now(),
  constraint feedback_one_per_user unique (lead_id, user_id)
);

-- =========================================================================
-- suppression: never contact these again (kept forever, Step 18)
-- =========================================================================
create table public.suppression (
  id         uuid primary key default gen_random_uuid(),
  phone_e164 text check (phone_e164 ~ '^\+[1-9][0-9]{6,14}$'),
  email      text,
  web_domain text,
  reason     text not null,      -- opt_out, wrong_contact, competitor, founder_skip, legal
  added_by   uuid default auth.uid() references public.profiles(user_id) on delete set null,
  added_at   timestamptz not null default now(),
  constraint suppression_has_key check (phone_e164 is not null or email is not null or web_domain is not null)
);
create unique index suppression_phone_uq  on public.suppression (phone_e164)   where phone_e164 is not null;
create unique index suppression_email_uq  on public.suppression (lower(email)) where email is not null;
create unique index suppression_domain_uq on public.suppression (web_domain)   where web_domain is not null;

-- =========================================================================
-- Operations: runs, costs, AI batches, AI cache, source health
-- =========================================================================
create table public.runs (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null check (kind in ('night','morning','sheet_sync','weekly','monthly','manual')),
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null default 'running' check (status in ('running','ok','partial','failed')),
  stats       jsonb not null default '{}'::jsonb,
  error       text
);
create index runs_kind_time_idx on public.runs (kind, started_at desc);

create table public.costs (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid references public.runs(id) on delete set null,
  provider      text not null check (provider in
                  ('gemini','openai','cache','google_places','google_search','pagespeed','other')),
  model         text,
  task          text not null,
  input_tokens  bigint not null default 0,
  output_tokens bigint not null default 0,
  calls         integer not null default 1,
  usd           numeric(12,6) not null default 0,
  inr           numeric(12,2) not null default 0,
  fallback_from text,             -- the planned provider when a fallback answered (Step 4)
  at            timestamptz not null default now()
);
create index costs_at_idx on public.costs (at);

create table public.llm_batches (
  id                uuid primary key default gen_random_uuid(),
  provider          text not null check (provider in ('gemini','openai')),
  provider_batch_id text not null,
  task              text not null,
  status            text not null default 'submitted' check (status in
                      ('submitted','running','completed','failed','expired','cancelled')),
  item_count        integer not null default 0,
  submitted_at      timestamptz not null default now(),
  completed_at      timestamptz,
  result_ref        text,          -- provider file name or local path of the results
  constraint llm_batches_uq unique (provider, provider_batch_id)
);

-- Money held for a submitted batch until its results are collected (Step 4).
create table public.llm_batch_reservations (
  id           bigserial primary key,
  llm_batch_id uuid references public.llm_batches(id) on delete cascade,
  reserved_inr numeric not null,
  released     boolean not null default false,
  created_at   timestamptz not null default now()
);

-- Cached AI answers (Step 4). The night run deletes expired rows.
create table public.llm_cache (
  key        text primary key,
  task       text not null,
  model      text not null,
  response   jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index llm_cache_expires_idx on public.llm_cache (expires_at);

-- One row per source, plus 'llm:gemini' and 'llm:openai' for the AI circuit breakers (Step 4).
create table public.source_health (
  source         text primary key,
  enabled        boolean not null default true,
  last_ok_at     timestamptz,
  last_error_at  timestamptz,
  last_error     text,
  blocked_until  timestamptz,
  recent_blocks  timestamptz[] not null default '{}',   -- newest first, keep 10 (Steps 5 and 18 count them)
  requests_today integer not null default 0,
  requests_day   date not null default ((now() at time zone 'Asia/Kolkata')::date)  -- day of requests_today
);

-- =========================================================================
-- sheet_snapshots: what we last wrote to each sheet (two-way sync, Step 13)
-- =========================================================================
create table public.sheet_snapshots (
  sheet      text not null check (sheet in ('master','caller')),
  lead_id    uuid not null references public.leads(id) on delete cascade,
  values     jsonb not null,
  written_at timestamptz not null default now(),
  primary key (sheet, lead_id)
);

-- =========================================================================
-- golden_labels, custom_queries, inbox_posts, saved_views
-- =========================================================================
create table public.golden_labels (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  label       text not null check (label in ('good','bad')),
  reasons     text,
  labeled_by  uuid default auth.uid() references public.profiles(user_id) on delete set null,
  at          timestamptz not null default now(),
  constraint golden_one_per_labeler unique (business_id, labeled_by)
);

create table public.custom_queries (
  id         uuid primary key default gen_random_uuid(),
  segment_id text not null references public.segments(id) on update cascade,
  query      text not null,
  status     text not null default 'new' check (status in ('new','running','done','failed')),
  created_by uuid default auth.uid() references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.inbox_posts (
  id         uuid primary key default gen_random_uuid(),
  url        text,
  text       text not null,
  segment_id text references public.segments(id) on update cascade,
  status     text not null default 'new' check (status in
               ('new','processed','researched','lead_created','rejected')),
  lead_id    uuid references public.leads(id) on delete set null,   -- the lead made from this post
  created_by uuid default auth.uid() references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.saved_views (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references public.profiles(user_id) on delete cascade,
  name       text not null,
  query      jsonb not null default '{}'::jsonb,   -- filters, sort and columns of the Leads page
  shared     boolean not null default false,
  created_at timestamptz not null default now()
);
create index saved_views_user_idx on public.saved_views (user_id);
```

### 2.6.1 Notes on 0001
- `gin_trgm_ops` is written as `extensions.gin_trgm_ops` because Supabase installs `pg_trgm` in that schema.
- **One open lead per business:** the partial unique index stops a second live lead for the same company. After a lead closes (for example `not_now`), a new cycle can start.
- **`wa_at` auto-fill:** marking a lead `contacted` without a date fills today's IST date.
- **Trigger-owned activities:** `leads_after_write` writes `lead_created`, `stage_change`, `grade_change` and (for app edits) `message_edited`. It reads `app.source` and `app.context` from `db.tx()` (2.3.1). App edits arrive with a user session, so `auth.uid()` is set and the source is `app`.
- **User columns default to `auth.uid()`** (`activities.user_id`, `feedback.user_id`, `suppression.added_by`, `golden_labels.labeled_by`, `custom_queries.created_by`, `inbox_posts.created_by`, `saved_views.user_id`). The app does not need to send them; engine inserts leave them empty.
- **Adding a registry source later** (for example `rera_maharashtra` in Step 5): new migration, same constraint name.
  ```sql
  alter table public.source_records
    drop constraint source_records_source_known,
    add constraint source_records_source_known check (source in
      ('overture','places','art_registry','osm','apna','grounded_search','gdelt',
       'careers_watch','adzuna','practo','legacy','legacy_skip','rera_maharashtra'));
  ```
- `channel` is `whatsapp` when a mobile number exists, `email` when only an email was found, `form` when only a contact form exists (Step 12).

---

## 2.7 Migration 0002: views and helper functions

Create `supabase/migrations/0002_views.sql`. Every view uses `security_invoker = true`, so the RLS rules of the person asking apply. The one exception is `v_leads_admin` (2.8.3).

Two naming rules the app relies on (Step 15.5.1):
- `v_leads_caller`, `v_leads_admin` and `v_pipeline` call the lead id `id`, like the `leads` table.
- `v_today`, `v_followups_due` and `v_funnel` call it `lead_id`.

```sql
-- 0002_views.sql : read models for the app, the sheets and reports

-- Best contact per business: has a phone, decision maker, mobile, verified, own website.
-- Skips do-not-contact rows and anything in suppression.
create or replace view public.v_primary_contact with (security_invoker = true) as
select distinct on (c.business_id)
  c.business_id, c.id as contact_id, c.name, c.role, c.phone_e164, c.phone_type,
  c.email, c.source, c.source_url, c.is_decision_maker, c.verified
from public.contacts c
where not c.do_not_contact
  and (c.phone_e164 is not null or c.email is not null)
  and not exists (select 1 from public.suppression su
                  where su.phone_e164 = c.phone_e164 or lower(su.email) = lower(c.email))
order by c.business_id,
         (c.phone_e164 is not null) desc,
         c.is_decision_maker desc,
         (c.phone_type = 'mobile') desc,
         c.verified desc,
         (c.source = 'website') desc,
         c.created_at;

-- Strongest active signal per business (same order as the sheet view in Step 13).
create or replace view public.v_top_signal with (security_invoker = true) as
select distinct on (g.business_id)
  g.business_id, g.id as signal_id, g.type, g.category, g.points,
  g.quote, g.url, g.observed_at, g.expires_at
from public.signals g
where g.expires_at > now()
order by g.business_id, g.points desc, g.observed_at desc;

-- Latest verified fact per business and field (lead page evidence, message writer).
create or replace view public.v_verified_facts with (security_invoker = true) as
select distinct on (f.business_id, f.field) f.*
from public.facts f
where f.verified
order by f.business_id, f.field, f.created_at desc;

-- Every lead column except deal_value_inr, plus business, score, top signal and best contact.
-- Callers and viewers read leads only through this view.
create or replace view public.v_leads_caller with (security_invoker = true) as
select
  l.id, l.business_id, l.segment_id, l.score_id, l.grade, l.pitch_mode, l.test_group, l.angle,
  l.channel, l.message, l.message_alt, l.email_subject, l.email_body, l.followup_d3, l.followup_d7,
  l.message_model, l.message_check_score, l.stage, l.owner_id, l.wa_at, l.call_at, l.d3_at, l.d7_at,
  l.meeting_at, l.next_step, l.due_at, l.skipped_until, l.regen_requested_at, l.notes,
  l.created_at, l.updated_at, l.last_activity_at,
  b.name, b.city, b.locality, b.country, b.website, b.web_domain, b.category, b.subcategory,
  sc.total, sc.judge_note,
  ts.type as top_signal_type, ts.quote as top_signal_quote, ts.url as top_signal_url,
  ts.observed_at as top_signal_at,
  pc.name as contact_name, pc.role as contact_role, pc.phone_e164, pc.phone_type,
  pc.source as phone_source, pc.email
from public.leads l
join public.businesses b on b.id = l.business_id
left join public.scores sc on sc.id = l.score_id
left join public.v_top_signal ts on ts.business_id = l.business_id
left join public.v_primary_contact pc on pc.business_id = l.business_id;

-- The same plus money, for admins. NOT security_invoker: it runs with its owner's rights so it
-- can read deal_value_inr, and it returns rows only when the person asking is an admin.
create or replace view public.v_leads_admin as
select v.*, l.deal_value_inr
from public.v_leads_caller v
join public.leads l on l.id = v.id
where public.auth_role() = 'admin';

-- The same plus money, for the engine (service role) only. Revoked from app users in 0003.
create or replace view public.v_pipeline with (security_invoker = true) as
select v.*, l.deal_value_inr
from public.v_leads_caller v
join public.leads l on l.id = v.id;

-- Today's send list (Step 15 Today page): new A and B leads, reachable, not skipped, best first.
create or replace view public.v_today with (security_invoker = true) as
select v.id as lead_id, v.business_id, v.name as company, v.city, v.country, v.segment_id,
       v.grade, v.total, v.pitch_mode, v.angle, v.test_group, v.channel,
       v.top_signal_type, v.top_signal_quote, v.top_signal_url, v.top_signal_at,
       v.contact_name, v.contact_role, v.phone_e164, v.phone_type, v.phone_source, v.email,
       v.message, v.message_alt, v.email_subject, v.email_body, v.created_at
from public.v_leads_caller v
where v.stage = 'new'
  and v.grade in ('A','B')
  and (v.skipped_until is null or v.skipped_until <= now())
  and (v.phone_e164 is not null or v.channel <> 'whatsapp')
  and not exists (select 1 from public.suppression su where su.web_domain = v.web_domain)
order by v.grade, v.total desc nulls last, v.created_at;

-- Day 3 and day 7 follow-ups due today or earlier (Step 15 Today page).
-- Only leads still at 'contacted' (no reply yet). Day 7 waits until day 3 was sent.
create or replace view public.v_followups_due with (security_invoker = true) as
select v.id as lead_id, v.name as company, v.segment_id, v.grade, v.contact_name, v.phone_e164,
       f.which, f.followup_text, f.due_on
from public.v_leads_caller v
cross join lateral (values
    ('d3', v.followup_d3, v.wa_at + 3, v.d3_at is null),
    ('d7', v.followup_d7, greatest(v.wa_at + 7, v.d3_at + 3), v.d3_at is not null and v.d7_at is null)
  ) as f(which, followup_text, due_on, is_open)
where v.stage = 'contacted'
  and v.wa_at is not null
  and f.is_open
  and f.due_on <= (now() at time zone 'Asia/Kolkata')::date
  and (v.skipped_until is null or v.skipped_until <= now())
order by f.due_on, v.grade, v.total desc nulls last;

-- One row per lead with the furthest stage it ever reached (Step 15 Insights).
-- History comes from stage_change activities, so a lead that later closed still counts.
create or replace view public.v_funnel with (security_invoker = true) as
with ranks(stage, rnk) as (
  values ('new', 0), ('contacted', 1), ('talking', 2), ('discovery_booked', 3),
         ('discovery_done', 3), ('proposal_sent', 4), ('won', 5), ('retainer', 5)
),
reached as (
  select l.id as lead_id,
         greatest(coalesce(max(r_now.rnk), 0), coalesce(max(r_hist.rnk), 0)) as max_rnk
  from public.leads l
  left join ranks r_now on r_now.stage = l.stage
  left join public.activities a on a.lead_id = l.id and a.type = 'stage_change'
  left join ranks r_hist on r_hist.stage = a.payload ->> 'to'
  group by l.id
)
select l.id as lead_id, l.segment_id, b.country, l.pitch_mode, l.angle, l.test_group, l.grade,
       ts.type as top_signal_type,
       (l.created_at at time zone 'Asia/Kolkata')::date as created_on,
       (r.max_rnk >= 1 or l.wa_at is not null) as reached_contacted,
       r.max_rnk >= 2 as reached_talking,
       r.max_rnk >= 3 as reached_discovery,
       r.max_rnk >= 4 as reached_proposal,
       r.max_rnk >= 5 as reached_won
from public.leads l
join public.businesses b on b.id = l.business_id
join reached r on r.lead_id = l.id
left join public.v_top_signal ts on ts.business_id = l.business_id;

-- This week's numbers (week starts Monday, IST). No money here.
create or replace view public.v_kpis_week with (security_invoker = true) as
with b as (
  select date_trunc('week', now() at time zone 'Asia/Kolkata')::date as week_start,
         (now() at time zone 'Asia/Kolkata')::date as today
)
select
  count(*) filter (where l.wa_at >= b.week_start)                                   as contacted_this_week,
  count(*) filter (where l.stage in ('talking','discovery_booked','discovery_done',
                                     'proposal_sent','won','retainer'))              as conversations,
  count(*) filter (where l.stage in ('discovery_booked','discovery_done',
                                     'proposal_sent','won','retainer'))              as discovery_calls,
  count(*) filter (where l.stage in ('proposal_sent','won','retainer'))              as proposals,
  count(*) filter (where l.stage in ('won','retainer'))                              as won,
  count(*) filter (where l.due_at < b.today and l.stage not in
                   ('won','retainer','lost','not_now','not_a_fit','wrong_contact'))  as overdue,
  count(*) filter (where l.stage = 'new')                                           as new_waiting
from public.leads l cross join b;

-- Daily AI and API spend in IST days. Same columns as Step 19.4.
create or replace view public.v_costs_daily with (security_invoker = true) as
select (at at time zone 'Asia/Kolkata')::date as day, provider, task,
       sum(calls) as calls, sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens,
       sum(usd)::numeric(12,4) as usd, sum(inr)::numeric(12,2) as inr
from public.costs
group by 1, 2, 3;

-- Source health with a computed status for the Engine page.
create or replace view public.v_source_health with (security_invoker = true) as
select h.*,
  case
    when not h.enabled then 'disabled'
    when h.blocked_until is not null and h.blocked_until > now() then 'blocked'
    when h.last_error_at is not null and (h.last_ok_at is null or h.last_error_at > h.last_ok_at) then 'error'
    when h.last_ok_at is null or h.last_ok_at < now() - interval '3 days' then 'stale'
    else 'ok'
  end as health
from public.source_health h;

-- Database size in MB (`nlead health` and the Engine page, 2.13).
create or replace function public.db_size_mb() returns numeric
language sql stable security definer set search_path = public as $$
  select round(pg_database_size(current_database()) / 1024.0 / 1024.0, 1)
$$;
```

---

## 2.8 Migration 0003: Row Level Security, grants and storage

### 2.8.1 Access matrix
| Data | admin (founder) | caller (Aditya) | viewer | engine (service role) |
|---|---|---|---|---|
| Leads without money: `v_leads_caller`, `v_today`, `v_followups_due`, `v_funnel`, `v_kpis_week` | read; edit allowed columns | read; edit allowed columns | read | all |
| `deal_value_inr` | read via `v_leads_admin`; write via admin server action | no | no | all |
| Businesses, contacts, signals, facts, scores, `v_verified_facts`, `v_top_signal` | read | read | read | all |
| Contacts `do_not_contact` (Wrong contact, Do not contact) | edit | edit | no | all |
| Manual `ads_running` signal | add | add | no | all |
| Pages: titles and links only (no text) | read | read | read | all |
| Source records | read | no | no | all |
| Activities | read, add | read, add | read | all |
| Feedback | read, add own | read, add own | read, add own | all |
| Suppression | read, add, delete | read, add | no | all |
| Settings | read, edit | no | no | all |
| Segments | read, edit | read | read | all |
| Runs, costs, batches, source health | read (plus source on/off) | no | no | all |
| Golden labels, custom queries, inbox | read, add, edit | no | no | all |
| Saved views | own and shared | own and shared | own and shared | all |
| `proposals` bucket | read, upload, delete | read, upload | no | all |
| `backups` bucket, sheet snapshots, AI cache and reservations | no | no | no | all |

### 2.8.2 The migration
Create `supabase/migrations/0003_rls.sql`:

```sql
-- 0003_rls.sql : Row Level Security, grants and storage

-- 1. RLS on every table -------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'settings','segments','businesses','source_records','signals','pages','facts','contacts',
    'scores','profiles','leads','activities','feedback','suppression','runs','costs',
    'llm_batches','llm_batch_reservations','llm_cache','source_health','sheet_snapshots',
    'golden_labels','custom_queries','inbox_posts','saved_views']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- 2. Nothing for anonymous visitors; nothing new for anyone by default ---------
revoke all on all tables    in schema public from anon;
revoke all on all sequences in schema public from anon;
alter default privileges for role postgres in schema public revoke all on tables    from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;

-- 3. Policies -------------------------------------------------------------------
-- profiles: own row; admins see all. Roles change only through the admin client (Step 15).
create policy profiles_select on public.profiles for select to authenticated
  using (user_id = auth.uid() or public.auth_role() = 'admin');
create policy profiles_update_self on public.profiles for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
revoke insert, update, delete on public.profiles from authenticated;
grant update (full_name) on public.profiles to authenticated;

-- settings and segments
create policy settings_admin_select on public.settings for select to authenticated
  using (public.auth_role() = 'admin');
create policy settings_admin_update on public.settings for update to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy segments_read on public.segments for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy segments_admin_update on public.segments for update to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

-- research tables: read for every app role
create policy businesses_read on public.businesses for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy contacts_read on public.contacts for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy signals_read on public.signals for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy facts_read on public.facts for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy scores_read on public.scores for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy source_records_admin on public.source_records for select to authenticated
  using (public.auth_role() = 'admin');

-- pages: titles and links for everyone in the app; the raw text stays with the engine
create policy pages_read on public.pages for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
revoke select on public.pages from authenticated;
grant select (id, business_id, url, fetched_at, http_status, render_mode, title, robots_allowed)
  on public.pages to authenticated;

-- contacts: Wrong contact and Do not contact set one flag (Step 15)
create policy contacts_flag on public.contacts for update to authenticated
  using (public.auth_role() in ('admin','caller'))
  with check (public.auth_role() in ('admin','caller'));
revoke update on public.contacts from authenticated;
grant update (do_not_contact, updated_at) on public.contacts to authenticated;

-- signals: ads_running is entered by hand on the lead page (Step 7.5.6)
create policy signals_manual_ads on public.signals for insert to authenticated
  with check (public.auth_role() in ('admin','caller') and type = 'ads_running' and source = 'manual');

-- leads: rows readable by app roles, editable by admin and caller; money hidden by column grants
create policy leads_read on public.leads for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy leads_edit on public.leads for update to authenticated
  using (public.auth_role() in ('admin','caller'))
  with check (public.auth_role() in ('admin','caller'));
revoke select, insert, update, delete on public.leads from authenticated;
grant select (id, business_id, segment_id, score_id, grade, pitch_mode, test_group, angle, channel,
              message, message_alt, email_subject, email_body, followup_d3, followup_d7,
              message_model, message_check_score, stage, owner_id, wa_at, call_at, d3_at, d7_at,
              meeting_at, next_step, due_at, skipped_until, regen_requested_at, notes,
              created_at, updated_at, last_activity_at)
  on public.leads to authenticated;
grant update (stage, wa_at, call_at, d3_at, d7_at, meeting_at, next_step, due_at, notes,
              message, message_alt, followup_d3, followup_d7, owner_id, skipped_until,
              regen_requested_at, last_activity_at, updated_at)
  on public.leads to authenticated;
-- deal_value_inr: no grant at all. Admin server actions write it with the service role (Step 15).

-- views
revoke all on public.v_pipeline from authenticated;            -- has money; engine only
grant select on public.v_leads_caller, public.v_leads_admin, public.v_today, public.v_followups_due,
                public.v_funnel, public.v_kpis_week, public.v_primary_contact, public.v_top_signal,
                public.v_verified_facts, public.v_costs_daily, public.v_source_health
  to authenticated;   -- base-table RLS still applies: costs and source health stay admin-only

-- activities
create policy activities_read on public.activities for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy activities_insert on public.activities for insert to authenticated
  with check (public.auth_role() in ('admin','caller') and user_id = auth.uid() and source = 'app');

-- feedback
create policy feedback_read on public.feedback for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy feedback_insert on public.feedback for insert to authenticated
  with check (user_id = auth.uid() and public.auth_role() in ('admin','caller','viewer'));
create policy feedback_update_own on public.feedback for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- suppression
create policy suppression_read on public.suppression for select to authenticated
  using (public.auth_role() in ('admin','caller'));
create policy suppression_insert on public.suppression for insert to authenticated
  with check (public.auth_role() in ('admin','caller') and added_by = auth.uid());
create policy suppression_delete on public.suppression for delete to authenticated
  using (public.auth_role() = 'admin');

-- operations: admin read; admin can switch a source on or off
create policy runs_admin    on public.runs        for select to authenticated using (public.auth_role() = 'admin');
create policy costs_admin   on public.costs       for select to authenticated using (public.auth_role() = 'admin');
create policy batches_admin on public.llm_batches for select to authenticated using (public.auth_role() = 'admin');
create policy health_admin  on public.source_health for select to authenticated using (public.auth_role() = 'admin');
create policy health_admin_update on public.source_health for update to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

-- golden labels, custom queries, inbox: admin
create policy golden_admin on public.golden_labels for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy custom_queries_admin on public.custom_queries for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy inbox_admin on public.inbox_posts for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

-- saved views: your own, plus any marked shared
create policy saved_views_read on public.saved_views for select to authenticated
  using (user_id = auth.uid() or shared);
create policy saved_views_own on public.saved_views for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- No policies at all (engine only): sheet_snapshots, llm_cache, llm_batch_reservations.

-- 4. Functions ------------------------------------------------------------------
revoke all on function public.db_size_mb() from public, anon;
grant execute on function public.db_size_mb() to authenticated, service_role;

-- 5. Storage: private buckets -----------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('proposals', 'proposals', false, 20971520,          -- 20 MB
   array['application/pdf','image/png','image/jpeg',
         'application/vnd.openxmlformats-officedocument.wordprocessingml.document']),
  ('backups', 'backups', false, 52428800, null)        -- 50 MB, the free-plan upload limit (verify at build)
on conflict (id) do nothing;

create policy proposals_read on storage.objects for select to authenticated
  using (bucket_id = 'proposals' and public.auth_role() in ('admin','caller'));
create policy proposals_upload on storage.objects for insert to authenticated
  with check (bucket_id = 'proposals' and public.auth_role() in ('admin','caller'));
create policy proposals_delete on storage.objects for delete to authenticated
  using (bucket_id = 'proposals' and public.auth_role() = 'admin');
-- 'backups' has no policies: only the service role (nlead backup, Step 14) can use it.
```

### 2.8.3 Why money is protected this way
- Every app user connects as the same Postgres role, `authenticated`. Column grants apply to that role, so not granting `deal_value_inr` hides it from **everyone in the app**, admins included.
- Admins read money through `v_leads_admin`. That view runs with its owner's rights (so it can see the column) and returns rows only when `auth_role() = 'admin'`. The Supabase linter flags it as a "security definer view"; that is intended.
- Writes to `deal_value_inr` happen only in admin server actions that check the role and then use the service role key on the server (Step 15).
- The engine connects as `postgres`, which bypasses RLS and grants. That is how the master sheet gets deal values.

### 2.8.4 Rules for every later migration
Section 2 of 0003 removes default access for anything created later. So when a later step adds a database object:
1. **Table:** enable RLS in the same migration. If the app must read it, add a policy and `grant select on public.<table> to authenticated;`.
2. **View:** always write `with (security_invoker = true)`, including on `create or replace view`. Postgres replaces a view's options on `create or replace`, so leaving the option out silently turns it off. Grant `select` to `authenticated` only if the app reads it.
3. **Money or raw page text in a view:** engine only. Never grant it to `authenticated`.
4. **Function the app calls:** `revoke all ... from public, anon;` then grant `execute` to `authenticated`.

---

## 2.9 Migration 0004: seed data

Create `supabase/migrations/0004_seed.sql`:

```sql
-- 0004_seed.sql : defaults. Safe to re-run (only inserts missing rows).

insert into public.settings (key, value) values
  -- A.12.1
  ('daily_cap_inr',                  '750'::jsonb),
  ('alert_pct',                      '80'::jsonb),
  ('research_per_day',               '300'::jsonb),
  ('fx_inr_per_usd',                 '88'::jsonb),
  ('tier',                           '"balanced"'::jsonb),
  ('sheet_sync_enabled',             'true'::jsonb),
  ('providers_enabled',              '{"gemini": true, "openai": false}'::jsonb),
  ('sources_enabled',                '{"overture": true, "places": true, "art_registry": true, "osm": true,
                                       "apna": true, "grounded_search": true, "gdelt": true,
                                       "careers_watch": true, "adzuna": false, "practo": false}'::jsonb),
  ('segments_enabled',               '{"clinics-in": true, "realestate-in": true, "education-in": true,
                                       "clinics-ae": true, "realestate-ae": true, "education-ae": true}'::jsonb),
  -- per-source and per-task daily caps (Steps 5, 7, 9)
  ('careers_watch.pages_per_day',    '500'::jsonb),
  ('grounded_search.per_day',        '160'::jsonb),
  ('gdelt.queries_per_day',          '30'::jsonb),
  ('ai.classify_per_day',            '1500'::jsonb),
  ('research.browser_pages_per_run', '40'::jsonb),
  ('practo.pages_per_day',           '150'::jsonb),
  ('places_details_cap_in',          '230'::jsonb),
  ('places_details_cap_global',      '30'::jsonb),
  -- queue priority bonus per segment (Step 8.7; Step 16 may change it)
  ('segment_weights',                '{"clinics-in": 0, "realestate-in": 0, "education-in": 0,
                                       "clinics-ae": 0, "realestate-ae": 0, "education-ae": 0}'::jsonb),
  -- state kept by later steps (seeded so plain updates work)
  ('overture_release',               'null'::jsonb),
  ('sheet_state',                    '{"master": {"state": "ok"}, "caller": {"state": "ok"}}'::jsonb),
  ('budget_alert_day',               'null'::jsonb),
  ('score_weights',                  '{}'::jsonb),
  ('score_weights_frozen',           'false'::jsonb)
on conflict (key) do nothing;

insert into public.segments (id, domain, country, display_name, enabled, daily_quota) values
  ('clinics-in',    'clinics',    'in', 'Clinics, India',     true, 80),
  ('realestate-in', 'realestate', 'in', 'Real estate, India', true, 60),
  ('education-in',  'education',  'in', 'Education, India',   true, 50),
  ('clinics-ae',    'clinics',    'ae', 'Clinics, UAE',       true, 40),
  ('realestate-ae', 'realestate', 'ae', 'Real estate, UAE',   true, 40),
  ('education-ae',  'education',  'ae', 'Education, UAE',     true, 30)
on conflict (id) do nothing;
-- Quotas add up to 300 = research_per_day. The engine copies each YAML into segments.config (Step 3.2).

insert into public.source_health (source, enabled) values
  ('overture', true), ('places', true), ('art_registry', true), ('osm', true), ('apna', true),
  ('grounded_search', true), ('gdelt', true), ('careers_watch', true), ('adzuna', false),
  ('practo', false), ('llm:gemini', true), ('llm:openai', false)
on conflict (source) do nothing;
```

Two switches start off on purpose:
- OpenAI (`providers_enabled.openai`, `llm:openai`): on only after the founder adds a working OpenAI key (Appendix C).
- Practo (`sources_enabled.practo`): on only after the founder reads Practo's terms (Step 5).

### 2.9.1 Create the first user (by hand, never in a migration)
Emails are personal data, so they never go into migrations.
1. Dev project, **Authentication > Users > Add user > Create new user**: the founder's email, a strong password, tick **Auto Confirm User**.
2. In the dev **SQL editor** (replace the email):
   ```sql
   update public.profiles set role = 'admin', full_name = 'Founder'
   where user_id = (select id from auth.users where email = 'FOUNDER_EMAIL_HERE');
   ```
3. Step 21 does the same in prod for the founder (`admin`) and Aditya (`caller`). Later users are invited from the app (Step 15).

---

## 2.10 Tests

### 2.10.1 Test users (dev only)
In the **dev** project create three users the same way as 2.9.1: `rls-admin@test.local`, `rls-caller@test.local`, `rls-viewer@test.local`, with roles `admin`, `caller` and `viewer`. Put their user ids in `engine/.env.dev` as `RLS_ADMIN_ID`, `RLS_CALLER_ID`, `RLS_VIEWER_ID`, and the dev session pooler string as `DATABASE_URL_DEV`. These four names are test-only, not part of A.12.7.

### 2.10.2 `supabase/tests/rls_test.sql`
The test adds one business and one lead, runs every check, then **rolls everything back**, so dev stays clean. Any broken rule raises an error.

```sql
-- rls_test.sql : run against DEV only
-- psql "$DATABASE_URL_DEV" -v ON_ERROR_STOP=1 -v admin=<uuid> -v caller=<uuid> -v viewer=<uuid> -f supabase/tests/rls_test.sql
begin;

-- Fixture (as the engine) -------------------------------------------------------
insert into public.businesses (id, segment_id, name, norm_name, country, city, status)
values ('00000000-0000-4000-8000-000000000001', 'clinics-in', 'Test Skin Clinic',
        'test skin clinic', 'in', 'Pune', 'qualified');
insert into public.leads (id, business_id, segment_id, grade, pitch_mode, deal_value_inr)
values ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001',
        'clinics-in', 'A', 'fit_only', 50000);

-- Triggers ------------------------------------------------------------------------
update public.leads set stage = 'contacted' where id = '00000000-0000-4000-8000-000000000002';
do $$
begin
  if (select wa_at from public.leads where id = '00000000-0000-4000-8000-000000000002') is null then
    raise exception 'FAIL: contacted without a date did not fill wa_at';
  end if;
  if (select count(*) from public.activities
      where lead_id = '00000000-0000-4000-8000-000000000002'
        and type in ('lead_created','stage_change')) <> 2 then
    raise exception 'FAIL: triggers did not log lead_created and stage_change';
  end if;
  begin
    insert into public.leads (business_id, segment_id, grade, pitch_mode)
    values ('00000000-0000-4000-8000-000000000001', 'clinics-in', 'B', 'fit_only');
    raise exception 'FAIL: a second open lead for one business was allowed';
  exception when unique_violation then null;   -- expected
  end;
end $$;

-- Anonymous visitors get nothing ----------------------------------------------------
set local role anon;
do $$
begin
  perform 1 from public.v_today limit 1;
  raise exception 'FAIL: anon can read v_today';
exception when insufficient_privilege then null;   -- expected
end $$;

-- Caller: no money, no costs, can read leads -----------------------------------------
set local role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :'caller', 'role', 'authenticated')::text, true);
do $$
begin
  begin
    perform deal_value_inr from public.leads limit 1;
    raise exception 'FAIL: caller can read leads.deal_value_inr';
  exception when insufficient_privilege then null;
  end;
  begin
    perform 1 from public.v_pipeline limit 1;
    raise exception 'FAIL: caller can read v_pipeline';
  exception when insufficient_privilege then null;
  end;
  if exists (select 1 from public.v_leads_admin) then
    raise exception 'FAIL: caller got rows from v_leads_admin';
  end if;
  if exists (select 1 from public.costs) then
    raise exception 'FAIL: caller can read costs';
  end if;
  if not exists (select 1 from public.v_leads_caller where id = '00000000-0000-4000-8000-000000000002') then
    raise exception 'FAIL: caller cannot read leads';
  end if;
end $$;

-- Viewer: cannot edit a lead --------------------------------------------------------
select set_config('request.jwt.claims', json_build_object('sub', :'viewer', 'role', 'authenticated')::text, true);
do $$
declare n int;
begin
  update public.leads set notes = 'x' where id = '00000000-0000-4000-8000-000000000002';
  get diagnostics n = row_count;
  if n > 0 then raise exception 'FAIL: viewer updated a lead'; end if;
end $$;

-- Admin: sees money through v_leads_admin ----------------------------------------------
select set_config('request.jwt.claims', json_build_object('sub', :'admin', 'role', 'authenticated')::text, true);
do $$
begin
  if (select deal_value_inr from public.v_leads_admin
      where id = '00000000-0000-4000-8000-000000000002') is distinct from 50000 then
    raise exception 'FAIL: admin cannot read money through v_leads_admin';
  end if;
end $$;

rollback;
```

### 2.10.3 `engine/tests/test_rls.py`
Runs the SQL file against dev. It skips when `DATABASE_URL_DEV` is missing, so CI without dev access still passes.

```python
import os
import pathlib
import subprocess

import pytest

SQL = pathlib.Path(__file__).parents[2] / "supabase/tests/rls_test.sql"


@pytest.mark.skipif(not os.getenv("DATABASE_URL_DEV"), reason="needs the dev database")
def test_rls_rules():
    env = os.environ
    cmd = ["psql", env["DATABASE_URL_DEV"], "-v", "ON_ERROR_STOP=1",
           "-v", f"admin={env['RLS_ADMIN_ID']}", "-v", f"caller={env['RLS_CALLER_ID']}",
           "-v", f"viewer={env['RLS_VIEWER_ID']}", "-f", str(SQL)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

---

## 2.11 Migration workflow

### 2.11.1 Push to dev
The CLI is already linked to dev (Step 1.6).
```
$ cd nument-leads
$ npx supabase@latest db push --dry-run    # lists 0001 to 0004
$ npx supabase@latest db push
$ cd engine && uv run pytest tests/test_rls.py -q
```
Pin the CLI version that worked in the README. Prod is pushed in Step 21, never earlier.

### 2.11.2 Rules
1. Files are named `NNNN_description.sql` and applied in number order. Verify at build that your CLI version accepts 4-digit prefixes; if not, rename to its timestamp format **before** the first push and never rename again.
2. Step 2 owns 0001 to 0004. Later steps add their own files (Step 13 sheet views, Step 16 learning tables, Step 19 cost views) and each takes **the next free number** on the day you build it. Two files must never share a number.
3. **Never edit a pushed migration.** Add the next number instead.
4. Dev first, run the tests, then prod (Step 21).
5. After every schema change, regenerate the web types with the command in Step 15.2.4.
6. Every new table and view follows 2.8.4.

---

## 2.12 Retention

Step 18.2.2 owns the retention table, and the monthly workflow runs `nlead health --prune` (Step 14). Step 2 only makes it cheap: `pages_fetched_idx`, `places_fetched_at` and the `costs` and `runs` time indexes are there for those deletes. One rule matters here because of the schema: Places content (`rating`, `review_count`) must be nulled after 30 days (A.4.4); the business row stays.

---

## 2.13 Size budget against the 500 MB free tier

`nlead health` prints `select public.db_size_mb()` every morning: a **warning at 300 MB** (decide) and an **alert at 400 MB** (act now).

Estimate at full volume, 300 businesses researched a day. Assumptions: about 5 pages per business; about 3 KB stored per page after Postgres compression; about 20 facts per business at 0.5 KB each. **Measure real sizes after week 1** and redo this table.

| Data (retention from Step 18.2.2) | Volume | Stored size |
|---|---|---|
| `pages.text` of non-leads, 90 days | about 1,500 pages a day, 135,000 in the window | 250 to 400 MB |
| `pages.text` of leads, 180 days | about 150 pages a day | 40 to 80 MB |
| `facts`, kept while the business exists | about 6,000 a day | grows 60 to 100 MB a month |
| `businesses` and `source_records` | about 60,000 and 120,000 rows | about 100 MB |
| Everything else | | under 50 MB in year one |

**What this means:** with the current retention, the free tier is likely full within 2 to 3 months at full volume. The founder picks one of two levers when the 300 MB warning appears:
1. **Shorter text retention:** keep page text 30 days for businesses that did not become leads (verification runs within a day of fetching, Step 10, and facts keep the quotes), and delete facts of rejected businesses after 90 days except the ones that explain the rejection.
2. **Supabase Pro:** about $25 a month for 8 GB (verify at build).

Size by table:
```sql
select relname, pg_size_pretty(pg_total_relation_size(relid)) as size
from pg_catalog.pg_statio_user_tables order by pg_total_relation_size(relid) desc;
```

---

## 2.14 Backups

The free plan has no downloadable backups or point-in-time recovery (verify at build), so we make our own:
- **Workflow and command:** `.github/workflows/backup.yml` and `nlead backup` (Step 14.5.6): weekly, encrypted with `BACKUP_PASSPHRASE`, uploaded to the private `backups` bucket and kept as a workflow artifact.
- **Bucket:** `backups` is created by 0003 with no policies, so only the service role can read or write it. Its 50 MB file limit matches the free-plan upload limit (verify at build). When a dump outgrows it, the workflow artifact is the copy that remains.
- **Restore drill:** once, on dev, in Step 21.
- **Not in the dump:** Auth users live in Supabase's `auth` schema. After a restore, recreate users and their roles as in 2.9.1.

---

## 2.15 Pitfalls
| Pitfall | What happens | Fix |
|---|---|---|
| Direct connection in CI | "Network is unreachable" (IPv6) | Session pooler, port 5432 |
| Port 6543 for the engine | Prepared statement errors; `app.source` lost | Port 5432 |
| A view without `security_invoker = true`, or recreated without it | RLS bypassed; everyone sees everything | 2.8.4 rule 2 |
| `select *` from `leads` in the app | `permission denied for column deal_value_inr` | Read `v_leads_caller` (or `v_leads_admin` for admins) |
| `.update(...).select()` on `leads` in supabase-js | Same error: RETURNING includes money | Update without `.select()`, then read the view |
| Code inserts `stage_change`, `grade_change`, `lead_created` or `message_edited` | Every change shows twice on the timeline | Only the triggers write these four (2.5.9) |
| `v_leads_caller` changes | `v_leads_admin` and `v_pipeline` still have the old column list | Recreate both in the same migration |
| A later table the app needs | `permission denied for table` | Grant it on purpose (2.8.4) |
| A new activity type, source or cost provider used by code but not in the checks | Insert fails | Add it to the check in a new migration first |
| Service role key in browser code | Anyone can read everything | Server code, engine env files and GitHub environment secrets only |
| Dev project paused | Engine runs fail to connect | Resume it in the dashboard; `nlead health` warns |
| "Today" computed in UTC | Wrong day between 00:00 and 05:30 IST | `now() at time zone 'Asia/Kolkata'` |
| Editing a pushed migration | Dev and prod drift apart silently | Always add a new numbered file |

## 2.16 Done when
- [ ] The six checks in 2.2 pass.
- [ ] `db.tx()` takes `source` and `context` (2.3.1).
- [ ] 0001 to 0004 are applied to **dev** with `npx supabase db push`, without errors.
- [ ] `select count(*) from public.segments` returns 6 and the quotas add up to 300.
- [ ] Every settings key in 0004 exists, with OpenAI and Practo off.
- [ ] The `proposals` and `backups` buckets exist and are private.
- [ ] The founder is `admin` in dev `profiles`.
- [ ] `supabase/tests/rls_test.sql` passes on dev (`uv run pytest tests/test_rls.py`).
- [ ] `select public.db_size_mb()` returns a number.

---

---

# Step 3: Segments configuration (domain x country)

## 3.1 Goal and outputs

**Goal:** describe each market (one domain in one country) in one YAML file, so the engine knows where to look, what counts as a buying signal, how to judge fit and ability to pay, and how to pitch. **Adding a market means adding a file, not changing code** (A.6.3.5).

**You need first:** Step 1 (engine package), Step 2 (`segments` table).

**Outputs:**

| Output | Path |
|---|---|
| Segment models, loader, helpers, DB sync | `engine/src/nument_engine/segments.py` |
| Six wave-1 segment files | `engine/segments/{segment_id}.yaml` |
| Default scoring numbers | `engine/config/scoring.yaml` |
| Global exclusions | `engine/config/exclusions.yaml` |
| Tests | `engine/tests/test_segments.py` |
| Guide for new segments | `docs/segments-guide.md` (copy of 3.9) |

## 3.2 How segments are used
1. Every engine run starts with `load_segments()`. It validates every `engine/segments/*.yaml` against the models in 3.4 and stops the run with a clear error if a file is wrong.
2. `sync_segments_to_db()` upserts each segment into `public.segments`:
   - `config` (the whole file as JSON) and `config_version` (a hash of the file), every run.
   - `enabled` = the file's `enabled` **and** `settings.segments_enabled[id]`, every run. The app's toggle writes both (Step 15), so they stay in step.
   - `daily_quota`: from the YAML on the **first** insert only. After that the founder changes it in the app (Step 15), and the engine reads the database value.
3. `engine/config/scoring.yaml` holds the default scoring numbers. A segment's `scoring:` block overrides any of them for that segment only. `scoring_config(seg)` returns the merged result (Step 11 reads it).
4. `engine/config/exclusions.yaml` applies to every segment (Step 8 rule R3, Step 10 competitor check).

Who reads what:

| Step | Keys |
|---|---|
| 5 Sources | `overture.categories`, `registries`, `osm.enabled`, `apna.pages_per_day`, `adzuna_enabled`, and `subcategory_for()` |
| 6 Universe | `cities`, `places.queries`, `places.details_per_day` |
| 7 Signals | `job_keywords`, `public_ask_queries`, `news_queries`, `signal_points`, `places.reviews_per_day` |
| 8 Pre-filter | `fit.categories` and `ticket_class` (R2, through `is_type_match()`), `size_rules` (R9) |
| 11 Scoring | `fit`, `ticket_class`, `can_pay.premium_price`, `scoring`, `angles` |
| 12 Messages | `angles` (each angle's `idea`), `packaged_outcome` |

## 3.3 The segment file, key by key

These key names are fixed. Change one only together with every step that reads it.

| Key | Type | Meaning |
|---|---|---|
| `id` | string | `{domain}-{country}`, for example `clinics-in`. The file is named `{id}.yaml` |
| `domain` | enum | `clinics`, `realestate`, `education`, `d2c`, `hospitality`, `auto`, `finance`, `wellness`, `firms` |
| `country` | string | ISO alpha-2, lowercase: `in`, `ae`, later `sa`, `qa`, `gb`, `sg`, `us`, `au` |
| `display_name` | string | Shown in the app |
| `enabled` | bool | Master switch in the file |
| `timezone`, `currency` | string | `Asia/Kolkata` and `INR`; `Asia/Dubai` and `AED`. Prices in `can_pay` use this currency |
| `quota.daily_research` | int | Starting daily research quota (see 3.2). Enabled segments must add up to at most `research_per_day` (300) |
| `cities[]` | list | `name`, `aliases` (other spellings in addresses), `bbox` as `[min_lng, min_lat, max_lng, max_lat]` (at most 2 degrees each way), `localities` (Places text search rotates through them, Step 6) |
| `overture.categories` | list | Overture taxonomy codes to pull. Codes marked `# verify at build` are not confirmed yet |
| `places.queries` | list | Text Search templates; `{city}` is required, `{locality}` optional |
| `places.details_per_day` | int | Daily Place Details calls for this segment. All India segments together at most 230, all others together at most 30 (3.7.7) |
| `places.reviews_per_day` | int | Daily Place Details calls with reviews (review pain, Step 7). Same totals |
| `registries[]` | list | `key` (adapter and `source_records.source` name), `name`, `url`, `status` (`ready` or `verify_at_build`), `subcategory` (set on every business from it), `notes` |
| `osm.enabled` | bool | OpenStreetMap gap fill (Step 6). Tags per domain live in the adapter (Step 5) |
| `apna.pages_per_day` | int | Apna job pages a day. India only; 0 elsewhere |
| `adzuna_enabled` | bool | Adzuna jobs API for this country, only after its coverage is checked |
| `job_keywords.frontdesk` | list | Job title words that create `hiring_frontdesk` signals |
| `job_keywords.builder` | list | Job title words that create `hiring_builder` signals |
| `job_keywords.exclude` | list | Titles to skip even when a keyword matches (for example `nurse`) |
| `public_ask_queries` | list | Grounded search queries for public asks for a vendor (Step 7) |
| `news_queries` | list | GDELT queries for launches, new branches and expansion (Step 7) |
| `size_rules.any_of[]` | list | Rule R9 passes if any rule is true (an active stated need also passes, Step 8). A rule is `source` (`business`, `fact`, `signal`, `registry`), `key`, optional `field` (the number inside a fact's value), `op`, `value` |
| `signal_points` | map | Per-type overrides of A.12.3 default points, for example `review_pain: 7` |
| `fit.categories` | list | Raw categories (Overture codes, Places types) that count as a type match |
| `fit.service_keywords` | list | Words in a verified `services` fact that count as a type match |
| `fit.min_reviews`, `fit.min_staff` | int | The size point of the fit gate (defaults 100 and 2) |
| `ticket_class` | map | Our subcategories in match order. Each has `match` (category codes, or lowercase words found as whole words in the name) and `points` (0 to 6, added to can-pay) |
| `can_pay.premium_price` | object | Thresholds in the segment currency: `consultation` (price items that mention "consult", optional) and `other` (every other price item) |
| `scoring` | map | Overrides of `config/scoring.yaml` for this segment only (deep merge; lists are replaced) |
| `packaged_outcome` | string | The packaged offer for this domain (A.2.2). The loader checks it |
| `angles[]` | list | `key`, `label`, `signals` (signal types, or `fit_only`), `idea` (one line the message writer receives) |

Rule operators (`op`): `>=`, `<=`, `==`, `!=`, `in`, `not_in`, `exists`.

**Angle rules (Step 11.8.2 picks them):** every segment has the six fixed codes `build_what_they_asked`, `frontdesk_load`, `missed_calls`, `ad_leads_cold`, `no_online_booking`, `slow_site`; exactly one angle listing `fit_only` (the segment default); and at least one listing a growth signal (`new_place`, `new_branch` or `news`).

## 3.4 Loader code

Create `engine/src/nument_engine/segments.py`:

```python
"""Segment configuration: one YAML file per domain x country (Step 3).

load_segments()         validated Segment objects, keyed by id
sync_segments_to_db()   upsert into public.segments
scoring_config(seg)     config/scoring.yaml with the segment's `scoring` overrides applied
load_yaml_config(name)  engine/config/<name>.yaml
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

ENGINE_DIR = Path(__file__).resolve().parents[2]
SEGMENTS_DIR = ENGINE_DIR / "segments"
CONFIG_DIR = ENGINE_DIR / "config"

Domain = Literal["clinics", "realestate", "education", "d2c", "hospitality",
                 "auto", "finance", "wellness", "firms"]
SignalType = Literal["public_ask", "tender", "hiring_builder", "hiring_frontdesk", "review_pain",
                     "ads_running", "no_booking", "slow_site", "new_place", "new_branch",
                     "news", "funding"]
Op = Literal[">=", "<=", "==", "!=", "in", "not_in", "exists"]

PACKAGED_OUTCOME = {   # A.2.2; must match
    "clinics": "AI front desk",
    "realestate": "AI lead qualifier and site-visit booking",
    "education": "AI admissions counsellor",
    "d2c": "AI support, order and cash-on-delivery confirmations",
    "hospitality": "AI enquiry to quote",
    "auto": "AI lead follow-up and service booking",
    "finance": "AI renewals and document chasing",
    "wellness": "AI bookings and renewals",
    "firms": "Custom AI workflows",
}
# Angle codes Step 11 picks by signal type (11.8.2). Every segment must define all of them.
REQUIRED_ANGLES = {"build_what_they_asked", "frontdesk_load", "missed_calls",
                   "ad_leads_cold", "no_online_booking", "slow_site"}
GROWTH_SIGNALS = {"new_place", "new_branch", "news"}


class City(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    bbox: tuple[float, float, float, float]          # min_lng, min_lat, max_lng, max_lat
    localities: list[str] = Field(min_length=1)

    @field_validator("bbox")
    @classmethod
    def _bbox_ok(cls, v):
        min_lng, min_lat, max_lng, max_lat = v
        if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError(f"bad bbox {v}: use [min_lng, min_lat, max_lng, max_lat]")
        if max_lng - min_lng > 2 or max_lat - min_lat > 2:
            raise ValueError(f"bbox {v} is wider than 2 degrees: split the city")
        return v


class Quota(BaseModel):
    daily_research: int = Field(ge=0, le=300)


class Overture(BaseModel):
    categories: list[str] = Field(min_length=1)


class Places(BaseModel):
    queries: list[str] = Field(min_length=1)
    details_per_day: int = Field(ge=0, le=230)
    reviews_per_day: int = Field(ge=0, le=230)

    @field_validator("queries")
    @classmethod
    def _has_city(cls, v):
        bad = [q for q in v if "{city}" not in q]
        if bad:
            raise ValueError(f"every query needs {{city}}: {bad}")
        return v


class Registry(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    url: str
    status: Literal["ready", "verify_at_build"]
    subcategory: str | None = None
    notes: str | None = None


class Osm(BaseModel):
    enabled: bool = False


class Apna(BaseModel):
    pages_per_day: int = Field(0, ge=0, le=2000)


class JobKeywords(BaseModel):
    frontdesk: list[str] = Field(min_length=1)
    builder: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    """business: a businesses column. fact: a verified fact (`field` = the number inside its value).
    signal: an active signal of type `key`. registry: a source record from registry `key` ('*' = any)."""
    source: Literal["business", "fact", "signal", "registry"]
    key: str
    field: str | None = None
    op: Op
    value: Any = None


class SizeRules(BaseModel):
    any_of: list[Rule] = Field(min_length=1)


class Fit(BaseModel):
    categories: list[str] = Field(min_length=1)
    service_keywords: list[str] = Field(default_factory=list)
    min_reviews: int = Field(100, ge=0)
    min_staff: int = Field(2, ge=0)


class TicketClass(BaseModel):
    match: list[str] = Field(min_length=1)
    points: int = Field(ge=0, le=6)


class PremiumPrice(BaseModel):
    consultation: float | None = Field(None, gt=0)
    other: float = Field(gt=0)


class CanPay(BaseModel):
    premium_price: PremiumPrice


class Angle(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    signals: list[SignalType | Literal["fit_only"]] = Field(min_length=1)
    idea: str


class Segment(BaseModel):
    id: str
    domain: Domain
    country: str = Field(pattern=r"^[a-z]{2}$")
    display_name: str
    enabled: bool = True
    timezone: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    quota: Quota
    cities: list[City] = Field(min_length=1)
    overture: Overture
    places: Places
    registries: list[Registry] = Field(default_factory=list)
    osm: Osm = Field(default_factory=Osm)
    apna: Apna = Field(default_factory=Apna)
    adzuna_enabled: bool = False
    job_keywords: JobKeywords
    public_ask_queries: list[str] = Field(default_factory=list)
    news_queries: list[str] = Field(default_factory=list)
    size_rules: SizeRules
    signal_points: dict[SignalType, float] = Field(default_factory=dict)
    fit: Fit
    ticket_class: dict[str, TicketClass] = Field(min_length=1)
    can_pay: CanPay
    scoring: dict[str, Any] = Field(default_factory=dict)
    packaged_outcome: str
    angles: list[Angle] = Field(min_length=8)

    @model_validator(mode="after")
    def _consistency(self):
        if self.id != f"{self.domain}-{self.country}":
            raise ValueError(f"id must be {self.domain}-{self.country}")
        if self.packaged_outcome != PACKAGED_OUTCOME[self.domain]:
            raise ValueError(f"packaged_outcome must be '{PACKAGED_OUTCOME[self.domain]}' (A.2.2)")
        keys = [a.key for a in self.angles]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate angle keys")
        missing = REQUIRED_ANGLES - set(keys)
        if missing:
            raise ValueError(f"missing angles that Step 11 picks: {sorted(missing)}")
        if sum("fit_only" in a.signals for a in self.angles) != 1:
            raise ValueError("exactly one angle must list fit_only")
        if not any(GROWTH_SIGNALS & set(a.signals) for a in self.angles):
            raise ValueError("one angle must list a growth signal (new_place, new_branch or news)")
        if self.country != "in" and self.apna.pages_per_day:
            raise ValueError("apna is India only")
        for sub in self.ticket_class:
            if not re.fullmatch(r"[a-z0-9_]+", sub):
                raise ValueError(f"ticket_class key {sub} must be lowercase snake_case")
        return self

    # ---- helpers for Steps 5, 6, 8 and 11 -------------------------------------
    def subcategory_for(self, category: str | None, name: str = "") -> str | None:
        """Our subcategory from a source category code or the business name.
        The first ticket class in file order with a matching entry wins."""
        cat, text = (category or "").lower(), name.lower()
        for sub, tc in self.ticket_class.items():
            for m in tc.match:
                if m == cat or re.search(rf"\b{re.escape(m)}\b", text):
                    return sub
        return None

    def is_type_match(self, category: str | None, subcategory: str | None) -> bool:
        """Rule R2 (Step 8) and the first half of the Step 11 type point."""
        return (category or "") in self.fit.categories or (subcategory or "") in self.ticket_class

    def ticket_points(self, subcategory: str | None) -> int:
        tc = self.ticket_class.get(subcategory or "")
        return tc.points if tc else 0

    def premium_threshold(self, item: str) -> float:
        """A verified price_point at or above this, in the segment currency, is premium evidence."""
        pp = self.can_pay.premium_price
        if pp.consultation is not None and "consult" in item.lower():
            return pp.consultation
        return pp.other

    def angle(self, key: str) -> Angle:
        return {a.key: a for a in self.angles}[key]

    def fit_only_angle(self) -> str:
        return next(a.key for a in self.angles if "fit_only" in a.signals)

    def growth_angle(self) -> str:
        return next(a.key for a in self.angles if GROWTH_SIGNALS & set(a.signals))


def load_yaml_config(name: str) -> dict:
    """engine/config/<name>.yaml (scoring, exclusions)."""
    return yaml.safe_load((CONFIG_DIR / f"{name}.yaml").read_text())


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def scoring_config(seg: Segment) -> dict:
    """Default scoring numbers with this segment's overrides applied (Step 11 reads this)."""
    return _deep_merge(load_yaml_config("scoring"), seg.scoring)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_segments(directory: Path = SEGMENTS_DIR, research_per_day: int = 300) -> dict[str, Segment]:
    segments: dict[str, Segment] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            seg = Segment.model_validate(yaml.safe_load(path.read_text()))
        except Exception as exc:  # noqa: BLE001  (show every problem in one message)
            raise SystemExit(f"Invalid segment file {path.name}: {exc}") from exc
        if path.stem != seg.id:
            raise SystemExit(f"File {path.name} must be named {seg.id}.yaml")
        if seg.id in segments:
            raise SystemExit(f"Duplicate segment id {seg.id}")
        segments[seg.id] = seg
    total = sum(s.quota.daily_research for s in segments.values() if s.enabled)
    if total > research_per_day:
        raise SystemExit(f"Segment quotas add up to {total}, more than research_per_day={research_per_day}")
    return segments


def sync_segments_to_db(conn, segments: dict[str, Segment], directory: Path = SEGMENTS_DIR) -> None:
    """Upsert every segment. daily_quota is written on the first insert only (the app owns it after)."""
    row = conn.execute("select value from public.settings where key = 'segments_enabled'").fetchone()
    switches = (row or {}).get("value") or {}
    for seg in segments.values():
        enabled = seg.enabled and bool(switches.get(seg.id, True))
        conn.execute(
            """
            insert into public.segments (id, domain, country, display_name, enabled, daily_quota,
                                         config, config_version)
            values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            on conflict (id) do update set
              domain = excluded.domain, country = excluded.country,
              display_name = excluded.display_name, enabled = excluded.enabled,
              config = excluded.config, config_version = excluded.config_version
            """,
            (seg.id, seg.domain, seg.country, seg.display_name, enabled, seg.quota.daily_research,
             json.dumps(seg.model_dump(mode="json")), _file_hash(directory / f"{seg.id}.yaml")),
        )
```

## 3.5 Default scoring numbers: `engine/config/scoring.yaml`

Step 11 owns the formula (11.1 to 11.5). This file holds its numbers so they can be tuned without code changes; Step 11 reads them through `scoring_config(seg)`. The defaults below are exactly the numbers in Step 11.

```yaml
# engine/config/scoring.yaml : default scoring numbers (Step 11 owns the formula)
# A segment's `scoring:` block overrides any value here for that segment (lists are replaced).
# Fixed in score.py, not here: grade cut-offs (A.12.9), signal decay steps, SCORE_VERSION.

fit:
  gate: 2                       # fit below 2 = grade D (reason fit_gate)
  bonus: {3: 10, 2: 5, 1: 0, 0: 0}

can_pay:
  cap: 30
  branches: [{min: 4, points: 8}, {min: 2, points: 6}]     # tiers: the first that matches counts
  staff:    [{min: 8, points: 6}, {min: 3, points: 4}]
  reviews:  [{min: 300, points: 6}, {min: 100, points: 4}]
  premium_price: 5              # a verified price_point at or above the segment's threshold
  pays_for_software: 3          # booking system, CRM, live chat, WhatsApp API provider, claimed Practo
  custom_website: 2             # live site on its own domain, not a free builder sub-domain
  funding: 6                    # an active funding signal
  # ticket class points (0 to 6) come from the segment's ticket_class

intent:
  cap: 40
  stack_bonus_per_type: 2       # for each signal type after the first
  stack_bonus_max: 4

reach:
  decision_maker_mobile: 1.00
  business_mobile: 0.85
  landline: 0.65
  email: 0.45
  form: 0.30
  none: 0.00

total:
  raw_max: 80                   # total = round(raw / raw_max * 100 * reach)

fit_only_max_pct: 10            # A.12.4
judge_top_share: 0.5            # the best half by total (and every A) goes to the top model
```

## 3.6 Global exclusions: `engine/config/exclusions.yaml`

Skipped in **every** segment: Step 8 rule R3 (`chains`, `hospital_keywords`, `max_branches`), R4 (`agency_keywords`) and the Step 10 competitor check (`competitors`). Names are matched case-insensitively as whole words in `norm_name`; domains exactly on `web_domain`. Verify the domains at build and extend the lists whenever the founder marks a lead "Not a fit" for being a chain, a hospital or an agency.

```yaml
# engine/config/exclusions.yaml : skipped in every segment
# Use full names. Short names that independents share (for example "max", "allen", "aster", "dlf")
# wrongly reject real clinics: "DLF Phase 4" is a Gurugram locality that appears in many names.
chains:
  # Healthcare, India
  - {name: apollo hospitals, domains: [apollohospitals.com, apollo247.com]}
  - {name: apollo clinic, domains: [apolloclinic.com]}
  - {name: apollo cradle, domains: []}
  - {name: apollo fertility, domains: []}
  - {name: fortis, domains: [fortishealthcare.com]}
  - {name: max healthcare, domains: [maxhealthcare.in]}
  - {name: manipal hospital, domains: [manipalhospitals.com]}
  - {name: narayana health, domains: [narayanahealth.org]}
  - {name: medanta, domains: []}
  - {name: motherhood hospital, domains: []}
  - {name: rainbow children, domains: []}
  - {name: cloudnine, domains: [cloudninecare.com]}
  - {name: indira ivf, domains: [indiraivf.com]}
  - {name: nova ivf, domains: [novaivffertility.com]}
  - {name: birla fertility, domains: [birlafertility.com]}
  - {name: ferty9, domains: []}
  - {name: oasis fertility, domains: []}
  - {name: milann, domains: []}
  - {name: kaya skin clinic, domains: [kaya.in]}
  - {name: kaya clinic, domains: [kaya.in]}
  - {name: vlcc, domains: [vlccwellness.com]}
  - {name: oliva skin, domains: [olivaclinic.com]}
  - {name: kolors, domains: []}
  - {name: dr batra, domains: []}
  - {name: clove dental, domains: [clovedental.in]}
  - {name: sabka dentist, domains: [sabkadentist.com]}
  # Healthcare, UAE
  - {name: aster dm, domains: [asterdmhealthcare.com]}
  - {name: aster clinic, domains: [asterclinic.ae]}
  - {name: aster hospital, domains: [asterhospitals.in]}
  - {name: nmc healthcare, domains: [nmc.ae]}
  - {name: mediclinic, domains: [mediclinic.ae]}
  - {name: burjeel, domains: [burjeel.com]}
  - {name: thumbay, domains: [thumbay.com]}
  - {name: cleveland clinic abu dhabi, domains: []}
  - {name: king's college hospital, domains: []}
  - {name: american hospital dubai, domains: []}
  - {name: prime hospital, domains: []}
  - {name: saudi german hospital, domains: []}
  # Real estate developers, big brokers and portals, India
  - {name: dlf limited, domains: [dlf.in]}
  - {name: godrej properties, domains: [godrejproperties.com]}
  - {name: lodha group, domains: [lodhagroup.in, lodhagroup.com]}
  - {name: macrotech developers, domains: []}
  - {name: prestige group, domains: [prestigeconstructions.com]}
  - {name: sobha limited, domains: [sobha.com]}
  - {name: brigade group, domains: [brigadegroup.com]}
  - {name: tata housing, domains: []}
  - {name: mahindra lifespaces, domains: []}
  - {name: oberoi realty, domains: []}
  - {name: puravankara, domains: []}
  - {name: anarock, domains: []}
  - {name: jll, domains: []}
  - {name: cbre, domains: []}
  - {name: knight frank, domains: []}
  - {name: colliers, domains: []}
  - {name: nobroker, domains: [nobroker.in]}
  - {name: square yards, domains: [squareyards.com]}
  - {name: housing.com, domains: [housing.com]}
  - {name: magicbricks, domains: [magicbricks.com]}
  - {name: 99acres, domains: [99acres.com]}
  - {name: proptiger, domains: [proptiger.com]}
  # Real estate developers and portals, UAE
  - {name: emaar properties, domains: [emaar.com]}
  - {name: damac properties, domains: [damacproperties.com]}
  - {name: nakheel, domains: [nakheel.com]}
  - {name: meraas, domains: []}
  - {name: aldar properties, domains: [aldar.com]}
  - {name: sobha realty, domains: [sobharealty.com]}
  - {name: azizi developments, domains: [azizidevelopments.com]}
  - {name: property finder, domains: [propertyfinder.ae]}
  - {name: bayut, domains: [bayut.com]}
  - {name: dubizzle, domains: [dubizzle.com]}
  # Education companies
  - {name: byju's, domains: [byjus.com]}
  - {name: unacademy, domains: [unacademy.com]}
  - {name: physics wallah, domains: [pw.live]}
  - {name: physicswallah, domains: [pw.live]}
  - {name: allen career institute, domains: [allen.ac.in]}
  - {name: aakash institute, domains: [aakash.ac.in]}
  - {name: fiitjee, domains: [fiitjee.com]}
  - {name: vedantu, domains: [vedantu.com]}
  - {name: upgrad, domains: [upgrad.com]}
  - {name: leverage edu, domains: [leverageedu.com]}
  - {name: idp education, domains: [idp.com]}
  - {name: leap scholar, domains: [leapscholar.com]}
  - {name: yocket, domains: []}
  - {name: gems education, domains: [gemseducation.com]}
  - {name: taaleem, domains: [taaleem.ae]}
  - {name: aldar academies, domains: [aldaracademies.com]}

hospital_keywords:            # whole words in the name. Small Indian clinics sometimes call themselves
  - hospital                  # a "hospital" (for example "dental hospital"): check R3 rejects in week 1
  - hospitals
  - medical college
  - institute of medical sciences
  - super speciality hospital
  - multispeciality hospital
  - nursing home

agency_keywords:              # in name, category or site title: they sell what we sell
  - digital marketing
  - marketing agency
  - seo agency
  - seo services
  - web design
  - web development
  - web solutions
  - app development
  - software development
  - software solutions
  - it services
  - it solutions
  - infotech
  - technologies pvt
  - ai solutions
  - automation agency
  - placement consultancy
  - staffing
  - recruitment agency

competitors:                  # software vendors and platforms in our space: never leads (names or domains)
  - aisensy
  - interakt
  - gallabox
  - wati
  - leadsquared
  - zoho
  - freshworks
  - haptik
  - yellow.ai
  - gupshup
  - kaleyra
  - exotel
  - knowlarity
  - practo

max_branches: 10              # 10 or more branches = a big chain (Steps 6 and 8)
```

> WhatsApp API providers (AiSensy, Interakt, Gallabox, Wati) are listed so they never become leads. They are also planned **partners**, which is handled outside the engine.

## 3.7 Wave-1 segment files

Bounding boxes are approximate city boxes in `[min_lng, min_lat, max_lng, max_lat]` order. **Verify at build** on a map. `clinics-in` is written out in full as the reference; the other five use the same keys in a compact style.

### 3.7.1 `engine/segments/clinics-in.yaml`

```yaml
# engine/segments/clinics-in.yaml : the reference segment (keys explained in Step 3.3)
id: clinics-in
domain: clinics
country: in
display_name: Clinics, India
enabled: true
timezone: Asia/Kolkata
currency: INR

quota:
  daily_research: 80            # first-sync value; afterwards the app owns it (Step 15)

cities:
  - name: Delhi
    aliases: [New Delhi, NCT of Delhi]
    bbox: [76.84, 28.40, 77.35, 28.88]
    localities: [Connaught Place, Saket, Hauz Khas, Greater Kailash, Lajpat Nagar, Defence Colony,
                 Vasant Kunj, Rajouri Garden, Punjabi Bagh, Janakpuri, Dwarka, Rohini, Pitampura,
                 Karol Bagh, Preet Vihar, Mayur Vihar, Kalkaji, Laxmi Nagar]
  - name: Gurugram
    aliases: [Gurgaon]
    bbox: [76.95, 28.38, 77.12, 28.53]
    localities: [DLF Phase 1, DLF Phase 4, Golf Course Road, Sohna Road, Sushant Lok, MG Road,
                 South City, Sector 14, Sector 29, Sector 56, Nirvana Country, Palam Vihar, Sector 82]
  - name: Noida
    aliases: [Greater Noida, Gautam Buddh Nagar]
    bbox: [77.29, 28.45, 77.50, 28.64]
    localities: [Sector 18, Sector 50, Sector 62, Sector 76, Sector 104, Sector 137, Greater Noida West]
  - name: Mumbai
    aliases: [Bombay, Mumbai Suburban]
    bbox: [72.77, 18.89, 72.99, 19.30]
    localities: [Andheri West, Andheri East, Bandra West, Khar, Santacruz, Juhu, Vile Parle, Powai,
                 Goregaon, Malad, Kandivali, Borivali, Dadar, Lower Parel, Worli, Colaba, Chembur,
                 Ghatkopar, Mulund]
  - name: Thane and Navi Mumbai
    aliases: [Thane, Navi Mumbai, New Bombay]
    bbox: [72.95, 18.98, 73.10, 19.30]
    localities: [Thane West, Vashi, Nerul, Kharghar, Belapur, Airoli]
  - name: Bengaluru
    aliases: [Bangalore, Bengaluru Urban]
    bbox: [77.46, 12.83, 77.78, 13.14]
    localities: [Indiranagar, Koramangala, HSR Layout, Whitefield, Jayanagar, JP Nagar, Malleshwaram,
                 Rajajinagar, Hebbal, Yelahanka, Marathahalli, Electronic City, BTM Layout, Bellandur,
                 Sarjapur Road, Banashankari, Basavanagudi, Frazer Town]
  - name: Pune
    aliases: [Pimpri Chinchwad, PCMC]
    bbox: [73.70, 18.40, 74.05, 18.70]
    localities: [Kothrud, Baner, Aundh, Wakad, Hinjewadi, Viman Nagar, Kalyani Nagar, Koregaon Park,
                 Hadapsar, Magarpatta, Shivajinagar, Deccan, Camp, Kharadi, Pimple Saudagar, Bavdhan]
  - name: Hyderabad
    aliases: [Secunderabad, Cyberabad]
    bbox: [78.30, 17.28, 78.62, 17.56]
    localities: [Banjara Hills, Jubilee Hills, Madhapur, Gachibowli, Kondapur, Kukatpally, Ameerpet,
                 Begumpet, Secunderabad, Somajiguda, Himayatnagar, Dilsukhnagar, LB Nagar, Miyapur,
                 Manikonda, Kompally]

overture:
  categories:
    - dental_clinic
    - dermatology
    - aesthetic_medicine
    - fertility_clinic
    - psychology
    - psychotherapy
    - counseling
    - behavioral_or_mental_health_clinic
    - hair_loss_center
    - physical_therapy          # verify at build
    - medical_skin_care         # verify at build

places:
  queries:
    - "dermatology clinic in {locality}, {city}"
    - "skin and hair clinic in {locality}, {city}"
    - "aesthetic clinic in {locality}, {city}"
    - "hair transplant clinic in {locality}, {city}"
    - "IVF centre in {locality}, {city}"
    - "fertility clinic in {locality}, {city}"
    - "dental clinic in {locality}, {city}"
    - "physiotherapy clinic in {locality}, {city}"
    - "psychologist clinic in {locality}, {city}"
  details_per_day: 90
  reviews_per_day: 90

registries:
  - key: art_registry
    name: ART and Surrogacy Registry (registered IVF clinics)
    url: https://registry.artsurrogacy.gov.in/clinic/list?type=register-clinic
    status: ready
    subcategory: ivf_fertility
    notes: About 4,767 clinics on one public page (checked 12 Nov 2026). Emails are written with [at] and [dot].
  - key: nabh
    name: NABH accredited small healthcare organisations
    url: https://nabh.co
    status: verify_at_build
    notes: Use only a public, robots-allowed list. Skip on a login or CAPTCHA.

osm:
  enabled: true
apna:
  pages_per_day: 120
adzuna_enabled: false

job_keywords:
  frontdesk: [receptionist, front desk, front office, patient coordinator, patient care coordinator,
              telecaller, tele caller, customer care executive, clinic coordinator,
              appointment coordinator, fertility counsellor, call centre executive]
  builder: [web developer, website developer, app developer, full stack developer, wordpress developer,
            automation, n8n, zapier, ai engineer, chatbot, crm executive, software developer]
  exclude: [nurse, doctor, dentist, physiotherapist, pharmacist, lab technician, ward boy, housekeeping]

public_ask_queries:
  - "looking for developer WhatsApp chatbot for clinic India"
  - "need website and online booking for my clinic India"
  - "clinic looking for appointment booking software developer"
  - "dermatologist looking for app developer"
news_queries:
  - '("new clinic" OR "opens" OR "inaugurates" OR "launches") (dermatology OR "skin clinic" OR IVF OR fertility OR dental) sourcecountry:IN'
  - '("new branch" OR "second centre" OR "expands") (clinic OR IVF OR "hair transplant") sourcecountry:IN'

size_rules:                     # Step 8.6; an active stated need also passes
  any_of:
    - {source: business, key: review_count, op: ">=", value: 100}
    - {source: business, key: branches_count, op: ">=", value: 2}
    - {source: registry, key: art_registry, op: exists}
    - {source: fact, key: staff_or_doctors, field: count, op: ">=", value: 2}

signal_points:                  # overrides of the A.12.3 defaults
  review_pain: 7
  no_booking: 4

fit:
  categories: [dental_clinic, dermatology, aesthetic_medicine, fertility_clinic, psychology,
               psychotherapy, counseling, behavioral_or_mental_health_clinic, hair_loss_center,
               physical_therapy, medical_skin_care,
               dentist, doctor, skin_care_clinic, physiotherapist]   # last four: Places types, verify at build
  service_keywords: [ivf, iui, fertility, dermatology, skin, laser, hair transplant, botox, fillers,
                     dental implants, aligners, root canal, physiotherapy, counselling, therapy]
  min_reviews: 100
  min_staff: 2

ticket_class:                   # match order matters: the first class that matches wins
  ivf_fertility:   {match: [fertility_clinic, ivf, fertility, infertility, test tube baby], points: 6}
  hair_transplant: {match: [hair_loss_center, hair transplant, hair restoration], points: 5}
  aesthetic:       {match: [aesthetic_medicine, medical_skin_care, aesthetic, cosmetic, laser, botox], points: 5}
  dermatology:     {match: [dermatology, skin_care_clinic, dermatologist, skin clinic, skin], points: 4}
  dental:          {match: [dental_clinic, dentist, dental, orthodontic], points: 3}
  physio:          {match: [physical_therapy, physiotherapist, physiotherapy, physio], points: 2}
  therapy_group:   {match: [psychology, psychotherapy, counseling, behavioral_or_mental_health_clinic,
                            psychologist, counselling, therapy], points: 2}

can_pay:
  premium_price: {consultation: 800, other: 20000}    # INR (Step 11.3)

scoring: {}                     # no overrides of config/scoring.yaml

packaged_outcome: AI front desk

angles:
  - {key: build_what_they_asked, label: Their own stated need, signals: [public_ask, tender, hiring_builder],
     idea: "Build exactly what they asked for, in their words, and mention one detail from their post."}
  - {key: frontdesk_load, label: Front desk overloaded, signals: [hiring_frontdesk],
     idea: "A WhatsApp assistant answers routine patient questions and books slots, so the front desk handles only real work."}
  - {key: missed_calls, label: Calls and messages missed, signals: [review_pain],
     idea: "Every call and WhatsApp answered in seconds, day and night, with a booking link."}
  - {key: ad_leads_cold, label: Ad enquiries going cold, signals: [ads_running],
     idea: "Every ad enquiry answered in 5 seconds and followed up until it books a consultation."}
  - {key: no_online_booking, label: No easy online booking, signals: [no_booking],
     idea: "Patients book on WhatsApp in under a minute, with reminders that cut no-shows."}
  - {key: slow_site, label: Slow mobile site, signals: [slow_site],
     idea: "A fast booking page with a WhatsApp button, so mobile visitors book instead of leaving."}
  - {key: new_branch_setup, label: New branch or clinic, signals: [new_branch, new_place, news],
     idea: "One front desk assistant for every branch from day one."}
  - {key: after_hours_enquiries, label: After-hours enquiries (no signal), signals: [fit_only],
     idea: "Answer patient questions and book slots after hours on WhatsApp."}
```

### 3.7.2 `engine/segments/realestate-in.yaml`

```yaml
id: realestate-in
domain: realestate
country: in
display_name: Real estate, India
enabled: true
timezone: Asia/Kolkata
currency: INR
quota: {daily_research: 60}

cities:
  - {name: Delhi, aliases: [New Delhi], bbox: [76.84, 28.40, 77.35, 28.88],
     localities: [Saket, Dwarka, Rohini, Janakpuri, Vasant Kunj, Greater Kailash, Rajouri Garden, Preet Vihar]}
  - {name: Gurugram, aliases: [Gurgaon], bbox: [76.95, 28.38, 77.12, 28.53],
     localities: [Golf Course Road, Golf Course Extension Road, Sohna Road, MG Road, Dwarka Expressway,
                  Sector 49, Sector 65, Sector 82]}
  - {name: Noida, aliases: [Greater Noida], bbox: [77.29, 28.45, 77.50, 28.64],
     localities: [Sector 18, Sector 62, Sector 75, Sector 137, Sector 150, Greater Noida West]}
  - {name: Mumbai, aliases: [Bombay], bbox: [72.77, 18.89, 72.99, 19.30],
     localities: [Andheri West, Bandra West, Powai, Goregaon, Malad, Borivali, Lower Parel, Worli, Chembur, Ghatkopar]}
  - {name: Thane and Navi Mumbai, aliases: [Thane, Navi Mumbai, Panvel], bbox: [72.95, 18.98, 73.10, 19.30],
     localities: [Thane West, Vashi, Kharghar, Panvel, Belapur]}
  - {name: Bengaluru, aliases: [Bangalore], bbox: [77.46, 12.83, 77.78, 13.14],
     localities: [Whitefield, Sarjapur Road, Hebbal, Yelahanka, Electronic City, HSR Layout, Koramangala,
                  Bannerghatta Road]}
  - {name: Pune, aliases: [Pimpri Chinchwad], bbox: [73.70, 18.40, 74.05, 18.70],
     localities: [Baner, Wakad, Hinjewadi, Kharadi, Viman Nagar, Hadapsar, Kothrud, Undri]}
  - {name: Hyderabad, aliases: [Secunderabad], bbox: [78.30, 17.28, 78.62, 17.56],
     localities: [Gachibowli, Kondapur, Kokapet, Madhapur, Kukatpally, Miyapur, Banjara Hills, Kompally]}

overture:
  categories:                   # none confirmed yet (Appendix F item 1)
    - real_estate               # verify at build
    - real_estate_agent         # verify at build
    - real_estate_service       # verify at build
    - real_estate_developer     # verify at build
    - property_management       # verify at build

places:
  queries:
    - "real estate developer in {city}"
    - "real estate agent in {locality}, {city}"
    - "property consultant in {locality}, {city}"
    - "real estate channel partner in {locality}, {city}"
  details_per_day: 60
  reviews_per_day: 60

registries:
  - {key: rera_maharashtra, name: MahaRERA agents and projects, url: "https://maharera.maharashtra.gov.in",
     status: verify_at_build, notes: "Mumbai and Pune. Stop on a CAPTCHA."}
  - {key: rera_haryana, name: HRERA (Gurugram), url: "https://haryanarera.gov.in", status: verify_at_build}
  - {key: rera_up, name: UP RERA (Noida), url: "https://www.up-rera.in", status: verify_at_build}
  - {key: rera_karnataka, name: Karnataka RERA (Bengaluru), url: "https://rera.karnataka.gov.in", status: verify_at_build}
  - {key: rera_telangana, name: Telangana RERA (Hyderabad), url: "https://rera.telangana.gov.in", status: verify_at_build}
  - {key: rera_delhi, name: Delhi RERA, url: "https://rera.delhi.gov.in", status: verify_at_build}

osm: {enabled: true}
apna: {pages_per_day: 100}
adzuna_enabled: false

job_keywords:
  frontdesk: [telecaller, tele sales, telesales, pre sales executive, presales, sales coordinator,
              customer relationship executive, inside sales, lead manager, crm executive, site visit coordinator]
  builder: [web developer, app developer, full stack developer, crm developer, automation, n8n, zapier,
            ai engineer, chatbot, salesforce developer]
  exclude: [civil engineer, site engineer, architect, accountant, driver, security guard]

public_ask_queries:
  - "real estate developer looking for CRM automation India"
  - "builder looking for WhatsApp lead management system"
  - "need app developer for real estate brokerage India"
news_queries:
  - '("launches" OR "new project" OR "new launch") ("real estate" OR developer OR realty) sourcecountry:IN'
  - '("opens office" OR "expands") (realty OR "real estate") sourcecountry:IN'

size_rules:
  any_of:
    - {source: business, key: review_count, op: ">=", value: 30}
    - {source: business, key: branches_count, op: ">=", value: 2}
    - {source: registry, key: "*", op: exists}

signal_points: {hiring_frontdesk: 9, ads_running: 6}

fit:
  categories: [real_estate, real_estate_agent, real_estate_service, real_estate_developer,
               property_management, real_estate_agency]          # last one: Places type, verify at build
  service_keywords: [residential projects, commercial projects, plots, villas, apartments, resale,
                     rentals, property management, channel partner]
  min_reviews: 30
  min_staff: 2

ticket_class:
  developer:         {match: [real_estate_developer, developers, builders, constructions, infra, buildcon], points: 6}
  broker:            {match: [real_estate_agent, real_estate_agency, realty, realtors, broker, brokerage,
                              property consultant, property consultants, channel partner], points: 2}
  property_services: {match: [property_management, real_estate_service, property management], points: 2}

can_pay:
  premium_price: {other: 7500000}      # INR 75 lakh, any listed property

scoring:
  can_pay:
    reviews: [{min: 100, points: 6}, {min: 30, points: 4}]     # brokers rarely reach 100 reviews

packaged_outcome: AI lead qualifier and site-visit booking

angles:
  - {key: build_what_they_asked, label: Their own stated need, signals: [public_ask, tender, hiring_builder],
     idea: "Build exactly what they asked for, in their words, tied to faster lead response."}
  - {key: frontdesk_load, label: Telecallers overloaded, signals: [hiring_frontdesk],
     idea: "A WhatsApp assistant replies to every portal and ad lead in seconds, qualifies it and books the site visit, so telecallers call only warm leads."}
  - {key: missed_calls, label: Leads not answered, signals: [review_pain],
     idea: "Every enquiry answered in seconds, day and night, and offered a site visit slot."}
  - {key: ad_leads_cold, label: Ad leads going cold, signals: [ads_running],
     idea: "Every ad lead gets an instant WhatsApp reply and follow-ups until it books a visit."}
  - {key: no_online_booking, label: Site visits not booked online, signals: [no_booking],
     idea: "Leads pick a site visit slot on WhatsApp, with a reminder the day before."}
  - {key: slow_site, label: Slow project pages, signals: [slow_site],
     idea: "A fast project page with WhatsApp booking, so mobile visitors book a visit instead of leaving."}
  - {key: new_branch_setup, label: New project or office, signals: [new_branch, new_place, news],
     idea: "Handle the launch rush: every enquiry for the new project answered and qualified automatically."}
  - {key: site_visit_followup, label: Site visit follow-up (no signal), signals: [fit_only],
     idea: "Follow up every enquiry until it books a site visit."}
```

### 3.7.3 `engine/segments/education-in.yaml`

```yaml
id: education-in
domain: education
country: in
display_name: Education, India
enabled: true
timezone: Asia/Kolkata
currency: INR
quota: {daily_research: 50}

cities:
  - {name: Delhi, aliases: [New Delhi], bbox: [76.84, 28.40, 77.35, 28.88],
     localities: [Mukherjee Nagar, Rajendra Nagar, Laxmi Nagar, Kalu Sarai, Karol Bagh, Dwarka, Rohini,
                  Saket, Lajpat Nagar]}
  - {name: Gurugram, aliases: [Gurgaon], bbox: [76.95, 28.38, 77.12, 28.53],
     localities: [Sector 14, Sushant Lok, Sohna Road, DLF Phase 4, Sector 56]}
  - {name: Noida, aliases: [Greater Noida], bbox: [77.29, 28.45, 77.50, 28.64],
     localities: [Sector 18, Sector 62, Sector 15, Greater Noida West]}
  - {name: Mumbai, aliases: [Bombay], bbox: [72.77, 18.89, 72.99, 19.30],
     localities: [Andheri West, Dadar, Vile Parle, Borivali, Chembur, Ghatkopar, Powai, Bandra West]}
  - {name: Bengaluru, aliases: [Bangalore], bbox: [77.46, 12.83, 77.78, 13.14],
     localities: [Jayanagar, Malleshwaram, Rajajinagar, Koramangala, HSR Layout, Marathahalli, Indiranagar]}
  - {name: Pune, aliases: [Pimpri Chinchwad], bbox: [73.70, 18.40, 74.05, 18.70],
     localities: [Deccan, Shivajinagar, Kothrud, Aundh, Viman Nagar, Wakad]}
  - {name: Hyderabad, aliases: [Secunderabad], bbox: [78.30, 17.28, 78.62, 17.56],
     localities: [Ameerpet, Dilsukhnagar, Kukatpally, Madhapur, Himayatnagar, Ashok Nagar]}

overture:
  categories:                   # none confirmed yet (Appendix F item 1)
    - educational_services      # verify at build
    - tutoring_center           # verify at build
    - test_preparation          # verify at build
    - language_school           # verify at build
    - vocational_and_technical_school   # verify at build
    - educational_consultant    # verify at build

places:
  queries:
    - "coaching institute in {locality}, {city}"
    - "JEE NEET coaching in {locality}, {city}"
    - "UPSC coaching in {locality}, {city}"
    - "CA coaching in {locality}, {city}"
    - "study abroad consultant in {locality}, {city}"
    - "IELTS coaching in {locality}, {city}"
    - "training institute in {locality}, {city}"
  details_per_day: 50
  reviews_per_day: 40

registries: []                  # none known yet; research public lists at build (Appendix F)

osm: {enabled: true}
apna: {pages_per_day: 80}
adzuna_enabled: false

job_keywords:
  frontdesk: [admission counsellor, admissions executive, academic counsellor, student counsellor,
              telecaller, front desk executive, centre coordinator, counsellor, career counsellor]
  builder: [lms developer, web developer, app developer, full stack developer, automation, n8n,
            ai engineer, chatbot, edtech developer]
  exclude: [teacher, faculty, lecturer, tutor, professor, content writer, driver, peon]

public_ask_queries:
  - "coaching institute looking for app developer India"
  - "need LMS and WhatsApp automation for coaching centre"
  - "study abroad consultancy looking for CRM automation"
news_queries:
  - '("new centre" OR "opens" OR "launches") (coaching OR "study abroad" OR academy) sourcecountry:IN'
  - '("expands" OR "new branch") (coaching OR institute) sourcecountry:IN'

size_rules:
  any_of:
    - {source: business, key: review_count, op: ">=", value: 50}
    - {source: business, key: branches_count, op: ">=", value: 2}

signal_points: {hiring_frontdesk: 9, ads_running: 5}

fit:
  categories: [educational_services, tutoring_center, test_preparation, language_school,
               vocational_and_technical_school, educational_consultant]
  service_keywords: [jee, neet, upsc, cat, clat, gate, ielts, pte, toefl, gre, gmat, sat, study abroad,
                     admissions counselling, coaching, test preparation]
  min_reviews: 50
  min_staff: 2

ticket_class:
  study_abroad:       {match: [educational_consultant, study abroad, overseas education, ielts, toefl,
                               gre, gmat, pte, visa], points: 5}
  coaching_institute: {match: [test_preparation, coaching, classes, jee, neet, upsc, ias, iit, cat, clat,
                               gate], points: 4}
  academy:            {match: [vocational_and_technical_school, academy, training institute, institute,
                               skill], points: 3}
  tutoring:           {match: [tutoring_center, language_school, tuition, tutorial, tutorials], points: 2}

can_pay:
  premium_price: {other: 50000}        # INR, any course or programme fee

scoring: {}

packaged_outcome: AI admissions counsellor

angles:
  - {key: build_what_they_asked, label: Their own stated need, signals: [public_ask, tender, hiring_builder],
     idea: "Build exactly what they asked for, in their words, tied to more admissions."}
  - {key: frontdesk_load, label: Counsellors overloaded, signals: [hiring_frontdesk],
     idea: "Instant WhatsApp replies with course details and fees, so counsellors call only students who are ready."}
  - {key: missed_calls, label: Enquiries not answered, signals: [review_pain],
     idea: "Every enquiry answered in seconds, day and night, with a demo class slot."}
  - {key: ad_leads_cold, label: Ad enquiries going cold, signals: [ads_running],
     idea: "Every ad enquiry gets an instant reply and follow-ups until the student books a demo."}
  - {key: no_online_booking, label: Demo classes not booked online, signals: [no_booking],
     idea: "Students book a demo class on WhatsApp, with reminders."}
  - {key: slow_site, label: Slow mobile site, signals: [slow_site],
     idea: "A fast course page with WhatsApp enquiry, so mobile visitors ask instead of leaving."}
  - {key: new_branch_setup, label: New centre, signals: [new_branch, new_place, news],
     idea: "Handle the new centre's enquiry rush without hiring extra counsellors."}
  - {key: admission_followup, label: Admission follow-up (no signal), signals: [fit_only],
     idea: "Answer and follow up every admission enquiry until enrolment."}
```

### 3.7.4 `engine/segments/clinics-ae.yaml`

```yaml
id: clinics-ae
domain: clinics
country: ae
display_name: Clinics, UAE
enabled: true
timezone: Asia/Dubai
currency: AED
quota: {daily_research: 40}

cities:
  - {name: Dubai, aliases: [Dubayy], bbox: [55.05, 24.95, 55.45, 25.35],
     localities: [Dubai Marina, JLT, Jumeirah, Umm Suqeim, Al Barsha, Business Bay, Downtown Dubai, DIFC,
                  Deira, Bur Dubai, Karama, Al Quoz, Dubai Healthcare City, Mirdif, Al Nahda, JVC,
                  Dubai Silicon Oasis, Motor City, Arabian Ranches]}
  - {name: Abu Dhabi, aliases: [Abu Zaby], bbox: [54.30, 24.20, 54.75, 24.55],
     localities: [Al Khalidiyah, Al Bateen, Corniche, Al Reem Island, Khalifa City, Mohammed Bin Zayed City,
                  Al Raha, Tourist Club Area, Al Mushrif, Yas Island]}
  - {name: Sharjah, aliases: [Ash Shariqah], bbox: [55.35, 25.25, 55.60, 25.42],
     localities: [Al Majaz, Al Nahda Sharjah, Al Khan, Al Taawun, Muwaileh, University City, Al Qasimia]}

overture:
  categories:
    - dental_clinic
    - dermatology
    - aesthetic_medicine
    - fertility_clinic
    - psychology
    - psychotherapy
    - counseling
    - behavioral_or_mental_health_clinic
    - hair_loss_center
    - physical_therapy          # verify at build
    - medical_skin_care         # verify at build

places:
  queries:
    - "dermatology clinic in {locality}, {city}"
    - "aesthetic clinic in {locality}, {city}"
    - "hair transplant clinic in {locality}, {city}"
    - "dental clinic in {locality}, {city}"
    - "IVF clinic in {locality}, {city}"
    - "physiotherapy clinic in {locality}, {city}"
    - "psychologist in {locality}, {city}"
  details_per_day: 14           # outside India the free allowance is about 30 a day per SKU (3.7.7)
  reviews_per_day: 10

registries:
  - {key: dha, name: Dubai Health Authority licensed facilities, url: "https://www.dha.gov.ae",
     status: verify_at_build, notes: "Only a public, robots-allowed list; Sheryan may need a login, skip if so."}
  - {key: doh_abu_dhabi, name: Department of Health Abu Dhabi facility directory, url: "https://www.doh.gov.ae",
     status: verify_at_build}
  - {key: mohap, name: Ministry of Health and Prevention (Sharjah and northern emirates), url: "https://mohap.gov.ae",
     status: verify_at_build}

osm: {enabled: true}
apna: {pages_per_day: 0}
adzuna_enabled: false           # only after Adzuna UAE coverage is checked

job_keywords:
  frontdesk: [receptionist, front desk, front office, patient coordinator, patient relations,
              call centre agent, customer service executive, clinic coordinator, insurance coordinator]
  builder: [web developer, app developer, full stack developer, automation, ai engineer, chatbot,
            crm specialist, software developer]
  exclude: [nurse, doctor, dentist, physiotherapist, pharmacist, lab technician, cleaner, driver]

public_ask_queries:
  - "clinic Dubai looking for WhatsApp booking system"
  - "dental clinic UAE need app developer"
  - "aesthetic clinic Dubai looking for CRM automation"
news_queries:
  - '("new clinic" OR "opens" OR "launches") (dermatology OR aesthetic OR dental OR IVF) (Dubai OR "Abu Dhabi" OR Sharjah)'
  - '("new branch" OR "expands") clinic (Dubai OR "Abu Dhabi")'

size_rules:
  any_of:
    - {source: business, key: review_count, op: ">=", value: 100}
    - {source: business, key: branches_count, op: ">=", value: 2}
    - {source: fact, key: staff_or_doctors, field: count, op: ">=", value: 2}

signal_points: {review_pain: 7, ads_running: 5}

fit:
  categories: [dental_clinic, dermatology, aesthetic_medicine, fertility_clinic, psychology,
               psychotherapy, counseling, behavioral_or_mental_health_clinic, hair_loss_center,
               physical_therapy, medical_skin_care,
               dentist, doctor, skin_care_clinic, physiotherapist]   # last four: Places types, verify at build
  service_keywords: [ivf, fertility, dermatology, skin, laser, hair transplant, botox, fillers,
                     dental implants, veneers, aligners, physiotherapy, counselling, therapy]
  min_reviews: 100
  min_staff: 2

ticket_class:
  ivf_fertility:   {match: [fertility_clinic, ivf, fertility], points: 6}
  hair_transplant: {match: [hair_loss_center, hair transplant], points: 5}
  aesthetic:       {match: [aesthetic_medicine, medical_skin_care, aesthetic, cosmetic, laser, botox, filler], points: 5}
  dermatology:     {match: [dermatology, skin_care_clinic, dermatologist, skin], points: 4}
  dental:          {match: [dental_clinic, dentist, dental, orthodontic], points: 3}
  physio:          {match: [physical_therapy, physiotherapist, physiotherapy, physio], points: 2}
  therapy_group:   {match: [psychology, psychotherapy, counseling, behavioral_or_mental_health_clinic,
                            psychologist, therapy], points: 2}

can_pay:
  premium_price: {consultation: 300, other: 3000}     # AED (Step 11.3)

scoring: {}

packaged_outcome: AI front desk

angles:
  - {key: build_what_they_asked, label: Their own stated need, signals: [public_ask, tender, hiring_builder],
     idea: "Build exactly what they asked for, in their words, and mention one detail from their post."}
  - {key: frontdesk_load, label: Front desk overloaded, signals: [hiring_frontdesk],
     idea: "A WhatsApp assistant answers patient questions in English and books appointments, so the front desk handles only real work."}
  - {key: missed_calls, label: Calls and WhatsApps missed, signals: [review_pain],
     idea: "Every call and WhatsApp answered in seconds, around the clock, with a booking link."}
  - {key: ad_leads_cold, label: Ad enquiries going cold, signals: [ads_running],
     idea: "Every ad enquiry answered in seconds and followed up until it books."}
  - {key: no_online_booking, label: No easy online booking, signals: [no_booking],
     idea: "Patients book on WhatsApp, with reminders that cut no-shows."}
  - {key: slow_site, label: Slow mobile site, signals: [slow_site],
     idea: "A fast booking page with a WhatsApp button, so mobile visitors book instead of leaving."}
  - {key: new_branch_setup, label: New branch or clinic, signals: [new_branch, new_place, news],
     idea: "One front desk assistant for every branch from day one."}
  - {key: after_hours_enquiries, label: After-hours enquiries (no signal), signals: [fit_only],
     idea: "Answer patient questions and book appointments after hours on WhatsApp."}
```

### 3.7.5 `engine/segments/realestate-ae.yaml`

```yaml
id: realestate-ae
domain: realestate
country: ae
display_name: Real estate, UAE
enabled: true
timezone: Asia/Dubai
currency: AED
quota: {daily_research: 40}

cities:
  - {name: Dubai, aliases: [Dubayy], bbox: [55.05, 24.95, 55.45, 25.35],
     localities: [Business Bay, Downtown Dubai, Dubai Marina, JLT, JVC, Al Barsha, Deira, Bur Dubai,
                  Dubai Hills, Palm Jumeirah, Arjan, Dubai South]}
  - {name: Abu Dhabi, aliases: [Abu Zaby], bbox: [54.30, 24.20, 54.75, 24.55],
     localities: [Al Reem Island, Yas Island, Saadiyat Island, Khalifa City, Al Raha, Corniche]}
  - {name: Sharjah, aliases: [Ash Shariqah], bbox: [55.35, 25.25, 55.60, 25.42],
     localities: [Al Majaz, Al Khan, Aljada, Muwaileh, Al Nahda Sharjah]}

overture:
  categories:
    - real_estate               # verify at build
    - real_estate_agent         # verify at build
    - real_estate_service       # verify at build
    - real_estate_developer     # verify at build
    - property_management       # verify at build

places:
  queries:
    - "real estate brokerage in {locality}, {city}"
    - "real estate agency in {locality}, {city}"
    - "property developer in {city}"
    - "property management company in {locality}, {city}"
  details_per_day: 9
  reviews_per_day: 7

registries:
  - {key: dld_brokers, name: Dubai Land Department registered brokers and offices, url: "https://dubailand.gov.ae",
     status: verify_at_build, notes: "Look for a public list or open data. Skip on a login or CAPTCHA."}
  - {key: adrec, name: Abu Dhabi Real Estate Centre, url: "https://www.adrec.gov.ae", status: verify_at_build}

osm: {enabled: true}
apna: {pages_per_day: 0}
adzuna_enabled: false

job_keywords:
  frontdesk: [telesales, call centre agent, lead qualifier, sales coordinator, admin assistant,
              customer service executive, leasing coordinator, crm executive]
  builder: [web developer, app developer, full stack developer, crm developer, automation,
            ai engineer, chatbot, salesforce developer]
  exclude: [commission only, driver, cleaner, security guard, civil engineer]

public_ask_queries:
  - "real estate brokerage Dubai looking for CRM automation"
  - "Dubai real estate agency need WhatsApp lead bot"
news_queries:
  - '("launches" OR "new project" OR "opens office") ("real estate" OR brokerage OR developer) (Dubai OR "Abu Dhabi" OR Sharjah)'

size_rules:
  any_of:
    - {source: business, key: review_count, op: ">=", value: 30}
    - {source: business, key: branches_count, op: ">=", value: 2}
    - {source: registry, key: "*", op: exists}

signal_points: {hiring_frontdesk: 9, ads_running: 6}

fit:
  categories: [real_estate, real_estate_agent, real_estate_service, real_estate_developer,
               property_management, real_estate_agency]          # last one: Places type, verify at build
  service_keywords: [off plan, offplan, secondary market, leasing, property management, holiday homes,
                     villas, apartments, commercial property]
  min_reviews: 30
  min_staff: 2

ticket_class:
  developer:         {match: [real_estate_developer, developer, developers, developments], points: 6}
  broker:            {match: [real_estate_agent, real_estate_agency, broker, brokers, brokerage, realty,
                              real estate agency, properties], points: 2}
  property_services: {match: [property_management, real_estate_service, holiday homes, property management], points: 2}

can_pay:
  premium_price: {other: 1500000}      # AED 1.5 million, any listed property

scoring:
  can_pay:
    reviews: [{min: 100, points: 6}, {min: 30, points: 4}]

packaged_outcome: AI lead qualifier and site-visit booking

angles:
  - {key: build_what_they_asked, label: Their own stated need, signals: [public_ask, tender, hiring_builder],
     idea: "Build exactly what they asked for, in their words, tied to faster lead response."}
  - {key: frontdesk_load, label: Telesales overloaded, signals: [hiring_frontdesk],
     idea: "Every Property Finder, Bayut and ad lead answered on WhatsApp in seconds, qualified and offered a viewing, so agents call only warm leads."}
  - {key: missed_calls, label: Leads not answered, signals: [review_pain],
     idea: "Every enquiry answered in seconds, day and night, and offered a viewing slot."}
  - {key: ad_leads_cold, label: Ad leads going cold, signals: [ads_running],
     idea: "Every ad lead gets an instant WhatsApp reply and follow-ups until it books a viewing."}
  - {key: no_online_booking, label: Viewings not booked online, signals: [no_booking],
     idea: "Leads pick a viewing slot on WhatsApp, with a reminder."}
  - {key: slow_site, label: Slow listing pages, signals: [slow_site],
     idea: "Fast listing pages with WhatsApp booking, so mobile visitors book a viewing instead of leaving."}
  - {key: new_branch_setup, label: New project or office, signals: [new_branch, new_place, news],
     idea: "Handle the launch rush: every enquiry answered and qualified automatically."}
  - {key: site_visit_followup, label: Viewing follow-up (no signal), signals: [fit_only],
     idea: "Follow up every enquiry until it books a viewing."}
```

### 3.7.6 `engine/segments/education-ae.yaml`

```yaml
id: education-ae
domain: education
country: ae
display_name: Education, UAE
enabled: true
timezone: Asia/Dubai
currency: AED
quota: {daily_research: 30}

cities:
  - {name: Dubai, aliases: [Dubayy], bbox: [55.05, 24.95, 55.45, 25.35],
     localities: [Al Barsha, Karama, Al Qusais, Deira, Bur Dubai, Knowledge Park, Academic City, JLT, Mirdif]}
  - {name: Abu Dhabi, aliases: [Abu Zaby], bbox: [54.30, 24.20, 54.75, 24.55],
     localities: [Tourist Club Area, Al Khalidiyah, Khalifa City, Mohammed Bin Zayed City, Al Mushrif]}
  - {name: Sharjah, aliases: [Ash Shariqah], bbox: [55.35, 25.25, 55.60, 25.42],
     localities: [Al Nahda Sharjah, Al Taawun, University City, Al Majaz, Muwaileh]}

overture:
  categories:
    - educational_services      # verify at build
    - tutoring_center           # verify at build
    - test_preparation          # verify at build
    - language_school           # verify at build
    - vocational_and_technical_school   # verify at build
    - educational_consultant    # verify at build

places:
  queries:
    - "training institute in {locality}, {city}"
    - "tutoring centre in {locality}, {city}"
    - "test preparation centre in {locality}, {city}"
    - "language institute in {locality}, {city}"
    - "education consultant in {locality}, {city}"
  details_per_day: 7
  reviews_per_day: 5

registries:
  - {key: khda, name: KHDA licensed training institutes (Dubai), url: "https://www.khda.gov.ae",
     status: verify_at_build, notes: "KHDA publishes directories of licensed institutes; check robots and format."}
  - {key: adek, name: ADEK (Abu Dhabi), url: "https://www.adek.gov.ae", status: verify_at_build}

osm: {enabled: true}
apna: {pages_per_day: 0}
adzuna_enabled: false

job_keywords:
  frontdesk: [admissions officer, admissions executive, student counsellor, academic counsellor,
              receptionist, front desk, customer service executive, telesales]
  builder: [lms developer, web developer, app developer, full stack developer, automation, ai engineer, chatbot]
  exclude: [teacher, trainer, lecturer, tutor, driver, cleaner]

public_ask_queries:
  - "training institute Dubai looking for app developer"
  - "tutoring centre UAE need WhatsApp booking automation"
news_queries:
  - '("new centre" OR "opens" OR "launches") (institute OR academy OR "training centre") (Dubai OR "Abu Dhabi" OR Sharjah)'

size_rules:
  any_of:
    - {source: business, key: review_count, op: ">=", value: 50}
    - {source: business, key: branches_count, op: ">=", value: 2}

signal_points: {hiring_frontdesk: 9, ads_running: 5}

fit:
  categories: [educational_services, tutoring_center, test_preparation, language_school,
               vocational_and_technical_school, educational_consultant]
  service_keywords: [ielts, pte, toefl, sat, gmat, gre, university admissions, study abroad,
                     tutoring, test preparation, professional certification]
  min_reviews: 50
  min_staff: 2

ticket_class:
  study_abroad:       {match: [educational_consultant, education consultant, study abroad,
                               university admissions], points: 5}
  coaching_institute: {match: [test_preparation, ielts, sat, gmat, gre, pte, toefl], points: 4}
  academy:            {match: [vocational_and_technical_school, training institute, academy, institute], points: 3}
  tutoring:           {match: [tutoring_center, language_school, tutoring, tuition, language institute], points: 2}

can_pay:
  premium_price: {other: 10000}        # AED, any course fee

scoring: {}

packaged_outcome: AI admissions counsellor

angles:
  - {key: build_what_they_asked, label: Their own stated need, signals: [public_ask, tender, hiring_builder],
     idea: "Build exactly what they asked for, in their words, tied to more enrolments."}
  - {key: frontdesk_load, label: Admissions team overloaded, signals: [hiring_frontdesk],
     idea: "Instant WhatsApp replies with course details and fees, so the team calls only students who are ready."}
  - {key: missed_calls, label: Enquiries not answered, signals: [review_pain],
     idea: "Every enquiry answered in seconds, with a trial class slot."}
  - {key: ad_leads_cold, label: Ad enquiries going cold, signals: [ads_running],
     idea: "Every ad enquiry gets an instant reply and follow-ups until the student books a trial."}
  - {key: no_online_booking, label: Trial classes not booked online, signals: [no_booking],
     idea: "Students book a trial or assessment on WhatsApp, with reminders."}
  - {key: slow_site, label: Slow mobile site, signals: [slow_site],
     idea: "A fast course page with WhatsApp enquiry, so mobile visitors ask instead of leaving."}
  - {key: new_branch_setup, label: New centre, signals: [new_branch, new_place, news],
     idea: "Handle the new centre's enquiry rush without hiring extra staff."}
  - {key: admission_followup, label: Admission follow-up (no signal), signals: [fit_only],
     idea: "Answer and follow up every enquiry until enrolment."}
```

### 3.7.7 Places daily caps across segments
The `places` caps above keep the totals inside the free allowances (A.10.2). Step 5 enforces the same totals at run time with the settings `places_details_cap_in` (230) and `places_details_cap_global` (30).

| Region | Details per day | Reviews per day | Free cap per day, per SKU |
|---|---|---|---|
| India | clinics 90 + real estate 60 + education 50 = 200 | 90 + 60 + 40 = 190 | 230 |
| UAE (abroad) | 14 + 9 + 7 = 30 | 10 + 7 + 5 = 22 | 30 |

Verify at build which pricing applies to the founder's billing account, and set the same caps as quotas in the Google Cloud console as a second safety net.

### 3.7.8 Verify-at-build checklist for the six files
1. Download Overture `taxonomy.csv` for the current release. Confirm every code in `overture.categories` and `fit.categories`, remove codes that do not exist, and delete the `# verify at build` comment from confirmed ones. Real estate and education have **no confirmed codes yet**.
2. Confirm the Places primary types used in `fit.categories` and `ticket_class` (`dentist`, `doctor`, `skin_care_clinic`, `physiotherapist`, `real_estate_agency`).
3. Draw every `bbox` on a map. It must cover the built-up area and not waste queries on sea or desert.
4. Open each `verify_at_build` registry. Check robots.txt, login and CAPTCHA. Set `status: ready` only if it is public and allowed (and add its key to `source_records_source_known`, 2.6.1); otherwise delete the entry.
5. Check that chain domains in `exclusions.yaml` are still the companies' real domains.
6. Run each `news_queries` entry once in the GDELT DOC API and each `public_ask_queries` entry once in grounded search; drop queries that return nothing useful.
7. Run `subcategory_for()` on 50 real business names per segment and fix `match` lists that pick the wrong class.

## 3.8 Tests

Create `engine/tests/test_segments.py`:

```python
from pathlib import Path

import pytest

from nument_engine.segments import (REQUIRED_ANGLES, SEGMENTS_DIR, load_segments, load_yaml_config,
                                    scoring_config)

WAVE1 = {"clinics-in", "realestate-in", "education-in", "clinics-ae", "realestate-ae", "education-ae"}


def test_all_segments_load():
    assert set(load_segments()) == WAVE1


def test_quotas_fit_research_per_day():
    assert sum(s.quota.daily_research for s in load_segments().values() if s.enabled) <= 300


def test_places_caps_inside_free_allowance():
    segs = list(load_segments().values())
    for field in ("details_per_day", "reviews_per_day"):
        india = sum(getattr(s.places, field) for s in segs if s.country == "in")
        abroad = sum(getattr(s.places, field) for s in segs if s.country != "in")
        assert india <= 230 and abroad <= 30, field


def test_every_segment_has_the_angles_step11_picks():
    for s in load_segments().values():
        assert REQUIRED_ANGLES <= {a.key for a in s.angles}, s.id
        assert s.fit_only_angle() and s.growth_angle()


def test_subcategory_ticket_and_premium_helpers():
    seg = load_segments()["clinics-in"]
    assert seg.subcategory_for("fertility_clinic") == "ivf_fertility"
    assert seg.subcategory_for(None, "Sunrise IVF and Fertility Centre") == "ivf_fertility"
    assert seg.subcategory_for(None, "City Physiotherapy Centre") == "physio"
    assert seg.ticket_points("ivf_fertility") == 6 and seg.ticket_points(None) == 0
    assert seg.premium_threshold("Consultation fee") == 800
    assert seg.premium_threshold("IVF package") == 20000
    assert seg.is_type_match("dentist", None) and not seg.is_type_match("restaurant", None)


def test_scoring_overrides_merge():
    base = load_yaml_config("scoring")
    merged = scoring_config(load_segments()["realestate-in"])
    assert merged["can_pay"]["reviews"][-1]["min"] == 30        # segment override
    assert merged["reach"] == base["reach"]                       # untouched default


def test_exclusions_file_shape():
    ex = load_yaml_config("exclusions")
    assert set(ex) == {"chains", "hospital_keywords", "agency_keywords", "competitors", "max_branches"}
    assert all(set(c) == {"name", "domains"} for c in ex["chains"])


def test_bad_id_is_rejected(tmp_path: Path):
    bad = (SEGMENTS_DIR / "clinics-in.yaml").read_text().replace("id: clinics-in", "id: clinic-in", 1)
    (tmp_path / "clinic-in.yaml").write_text(bad)
    with pytest.raises(SystemExit):
        load_segments(tmp_path)
```

Run: `cd engine && uv run pytest tests/test_segments.py -q`.

## 3.9 How to add a new segment (checklist)
Copy this into `docs/segments-guide.md`.

1. **Id:** `{domain}-{country}`, for example `clinics-sa` or `d2c-in`.
2. **Copy the closest file** (for example `clinics-ae.yaml`) to `engine/segments/<id>.yaml`; change `id`, `domain`, `country`, `display_name`, `timezone`, `currency`.
3. **Cities:** name, aliases, a bbox under 2 degrees each way, 5 to 20 localities.
4. **Overture categories:** from `taxonomy.csv`; mark unsure ones `# verify at build`.
5. **Places:** 3 to 8 queries in local wording; daily caps that keep the regional totals inside 3.7.7.
6. **Registries:** public registries for that country and domain, status `verify_at_build` until checked.
7. **Sources:** `osm.enabled`, `apna.pages_per_day` (India only, else 0), `adzuna_enabled` (only after checking coverage).
8. **Job keywords:** words local job posts really use, plus `exclude`.
9. **Public ask and news queries:** 2 to 4 each, tested once.
10. **Size rules and fit:** local review and staff thresholds; `fit.categories` and `service_keywords`.
11. **Ticket classes and premium price:** subcategories in match order with 0 to 6 points; price thresholds in the local currency.
12. **Exclusions:** add the market's big chains, platforms and corporates to `config/exclusions.yaml`.
13. **Pitch:** the domain's `packaged_outcome` (A.2.2); 8 angles with the six fixed codes, a growth angle and one `fit_only` angle.
14. **Compliance:** read the country's data law and telemarketing rules (Step 18) before enabling.
15. **Quota:** keep the enabled total at or under `research_per_day`.
16. `uv run pytest tests/test_segments.py`, commit, then `nlead universe --segment <id> --limit 50 --dry-run --env dev`.
17. Label 20 businesses from the new segment in the golden set (Step 17) before enabling it in prod.
18. Enable it in prod with a small quota (for example 20 a day) and watch reply rates for 2 weeks (Step 23).

## 3.10 Pitfalls
| Pitfall | Fix |
|---|---|
| A bbox too large (a whole state) | Overture queries get slow and noisy; split into cities under 2 degrees |
| Guessed Overture codes | Wrong codes return nothing, silently; confirm in `taxonomy.csv` and check counts in Step 6 |
| Quotas adding up to more than 300 | The loader stops the run; lower another segment |
| A short exclusion name (for example "dlf" or "max") | It rejects real businesses; use full names plus domains |
| A broad `ticket_class` word placed early (for example "skin" above "laser") | The wrong class wins; put specific classes first and test with `subcategory_for()` |
| Copying a file but forgetting to rename `id` | Loader error "must be named"; rename both |
| Places caps above the free allowance | Real money is spent; the test in 3.8 catches it |
| An angle code renamed in one file | Step 11 cannot find it; the loader requires the six fixed codes |
| A registry that needs a login or CAPTCHA | Never use it (A.4.2); delete it from the file |

## 3.11 Done when
- [ ] `engine/src/nument_engine/segments.py` exists with the models, helpers, `load_segments()`, `scoring_config()`, `load_yaml_config()` and `sync_segments_to_db()`.
- [ ] `engine/config/scoring.yaml` and `engine/config/exclusions.yaml` exist with the shapes in 3.5 and 3.6.
- [ ] All six wave-1 files load and `tests/test_segments.py` passes.
- [ ] Quotas add up to 300 or less; Places caps stay inside 3.7.7.
- [ ] Checklist 3.7.8 is done: codes confirmed, bboxes checked, registries `ready` or removed, queries tested.
- [ ] `sync_segments_to_db()` on dev fills `segments.config` and `config_version` for all six rows and leaves `daily_quota` alone on later runs.
- [ ] Setting `settings.segments_enabled["education-ae"]` to false and syncing sets that segment's `enabled` to false.
- [ ] `docs/segments-guide.md` contains the checklist from 3.9.

---

# Step 4: AI router (Gemini + OpenAI)

**Goal:** one module that every pipeline step calls to use AI. It picks a model for each task from a **fallback chain**, enforces a JSON shape, retries safely, fails over to the next provider when one is down, caches answers, logs every rupee spent and which provider did the work, and refuses work that would break the ₹750 daily cap.

**Founder requirement (12 Nov 2026):** OpenAI may be unavailable at times. So:
1. Every task has a `primary` model and a list of `fallbacks`.
2. **Gemini alone must be able to run every task.** Every chain contains at least one Gemini model, and the system must pass all tests and the golden-set eval with OpenAI switched off.
3. Local testing and all automated tests run on **Gemini only**.

**Why this matters:** AI is almost the whole running cost, and AI is the only part of the system that can invent things. Putting every call through one door makes cost, quality, safety and provider outages controllable in one place.

**You need first:**
- Step 1 done (repo, `engine/` package, `settings.py`, `logging.py`, `db.py`).
- Step 2 done (tables `costs`, `llm_batches`, `settings`, `runs`, `source_health` exist).
- `GEMINI_API_KEY` in `engine/.env` (local) and in GitHub Actions secrets (Step 14). `OPENAI_API_KEY` is optional: if it is missing, OpenAI is simply skipped.
- Keys on **paid** tiers. Free tiers may use our inputs for training and have tiny rate limits.

**You will create:**
```
engine/config/tasks.yaml
engine/config/prices.yaml
engine/prompts/*.md                 (texts are in the Appendices; this step builds the loader)
engine/src/nument_engine/llm/__init__.py
engine/src/nument_engine/llm/types.py
engine/src/nument_engine/llm/prompts.py
engine/src/nument_engine/llm/gemini.py
engine/src/nument_engine/llm/openai_provider.py
engine/src/nument_engine/llm/availability.py     # providers_enabled, key checks, circuit breaker
engine/src/nument_engine/llm/batch.py
engine/src/nument_engine/llm/router.py
engine/src/nument_engine/budget.py
engine/tests/test_llm_router.py
engine/tests/test_llm_fallback.py
engine/tests/test_budget.py
```

---

## 4.1 Design overview

### 4.1.1 One call path for every task
```
pipeline step
   |
   v
router.run(task="judge_lead", inputs={...})                         # sync call
router.submit_batch(task, items=[...]) / router.collect_batches()   # batch calls
   |
   |-- 1. load task config (tasks.yaml) for the active tier ("balanced")
   |-- 2. render the prompt file with jinja2 (prompts/<task>.md)
   |-- 3. cache lookup (hash of task + prompt version + rendered prompt)
   |-- 4. walk the chain [primary, fallback 1, fallback 2, ...]:
   |        skip if provider disabled in settings.providers_enabled
   |        skip if the provider's API key is missing
   |        skip if the provider's circuit breaker is open (cooling off)
   |-- 5. budget guard for the chosen model: estimate, compare with today's spend, the cap,
   |        and the optional per-run cap (--max-spend-inr)
   |-- 6. provider call with timeout + retries
   |        on failure after retries: record the failure (may trip the breaker), go to the next model
   |-- 7. parse + validate JSON against the task's pydantic model (one repair retry)
   |-- 8. write a cost row: provider and model actually used, and fallback_from if not the primary
   |-- 9. store in cache, return a typed result
```

### 4.1.2 Rules the router enforces
1. A pipeline step never imports `google.genai` or `openai` directly. Only `llm/gemini.py` and `llm/openai_provider.py` do.
2. Every task returns a **pydantic object**. `write_message` returns an object with a `message` field.
3. Every call writes a `costs` row, including cache hits (with `usd = 0`, `calls = 1`, `provider = "cache"`), so usage is countable.
4. If the budget guard says no, the router raises `BudgetExceeded`. The calling step catches it, records the skip in `runs.stats`, and moves on.
5. If every model in a chain is unavailable or fails, the router raises `AllProvidersDown`. The step records it and moves on. The run ends `partial`, not `failed`.
6. Model ids live only in `tasks.yaml`. Changing a model is a one-line config change plus an eval run (Step 17).
7. The same pydantic schema and the same prompt file are used whichever provider answers.

---

## 4.2 Task registry: `engine/config/tasks.yaml`

### 4.2.1 Fields explained
| Field | Meaning |
|---|---|
| `primary` | `{provider, model}` tried first |
| `fallbacks` | Ordered list of `{provider, model}` tried next. **Must include at least one Gemini model** (validated at startup) |
| `mode` | `sync` (call now) or `batch` (submit at night, collect in the morning, about half price) |
| `schema` | Name of the pydantic model in `nument_engine.models` that the output must match |
| `prompt` | Prompt file in `engine/prompts/` |
| `max_output_tokens` | Hard cap on output tokens |
| `temperature` | 0 to 1. Low for extraction, a bit higher for writing |
| `thinking` | `off`, `low`, `medium`, `high` (mapped per provider in 4.6 and 4.7) |
| `tools` | `[]` or `[web_search]`. `web_search` means Gemini's `google_search` tool or OpenAI's `web_search` tool, depending on who answers |
| `priority` | 1 (never drop) to 6 (drop first) when the budget is tight |
| `est_input_tokens`, `est_output_tokens` | Used by the budget guard before the call |
| `cache_ttl_days` | How long a cached answer stays valid. 0 means never cache |
| `timeout_s` | Per call timeout |
| `max_retries` | Retries on network errors, 429, 500, 503 before failing over |

### 4.2.2 Full file (Balanced tier, other tiers ready to switch)
```yaml
# engine/config/tasks.yaml
# Active tier comes from settings.tier (default "balanced").
# Model ids change often: verify at build with `nlead health --models` (4.4).
# Rule: every chain must contain at least one gemini model (Gemini-only mode must work).

models:                                       # short names used below
  g_pro:   { provider: gemini, model: gemini-3.1-pro }          # verify at build
  g_flash: { provider: gemini, model: gemini-3-flash }          # verify at build
  g_lite:  { provider: gemini, model: gemini-3.1-flash-lite }   # verify at build
  o_top:   { provider: openai, model: gpt-5.4 }                 # verify at build
  o_mini:  { provider: openai, model: gpt-5-mini }              # verify at build
  o_nano:  { provider: openai, model: gpt-5-nano }              # verify at build

tiers:
  balanced:
    classify_signal:
      primary: g_lite
      fallbacks: [g_flash, o_nano]
      mode: sync
      schema: SignalClassification
      prompt: classify_signal.md
      max_output_tokens: 400
      temperature: 0.0
      thinking: off
      tools: []
      priority: 4
      est_input_tokens: 2000
      est_output_tokens: 300
      cache_ttl_days: 30
      timeout_s: 30
      max_retries: 3

    classify_news:
      primary: g_lite
      fallbacks: [g_flash, o_nano]
      mode: sync
      schema: NewsClassification
      prompt: classify_news.md
      max_output_tokens: 400
      temperature: 0.0
      thinking: off
      tools: []
      priority: 5
      est_input_tokens: 1500
      est_output_tokens: 300
      cache_ttl_days: 30
      timeout_s: 30
      max_retries: 3

    classify_page_change:
      primary: g_lite
      fallbacks: [g_flash, o_nano]
      mode: sync
      schema: PageChangeClassification
      prompt: classify_page_change.md
      max_output_tokens: 400
      temperature: 0.0
      thinking: off
      tools: []
      priority: 4
      est_input_tokens: 2000
      est_output_tokens: 300
      cache_ttl_days: 0
      timeout_s: 30
      max_retries: 3

    extract_facts:
      primary: g_flash
      fallbacks: [g_lite, o_mini]             # batch on whichever is available (4.10)
      mode: batch
      schema: ExtractedFacts
      prompt: extract_facts.md
      max_output_tokens: 2500
      temperature: 0.0
      thinking: low
      tools: []
      priority: 3
      est_input_tokens: 16000
      est_output_tokens: 2000
      cache_ttl_days: 14
      timeout_s: 120
      max_retries: 2

    verify_flagged:
      primary: g_flash
      fallbacks: [o_mini, g_lite]
      mode: sync
      schema: FlaggedVerification
      prompt: verify_flagged.md
      max_output_tokens: 600
      temperature: 0.0
      thinking: low
      tools: []
      priority: 3
      est_input_tokens: 4000
      est_output_tokens: 500
      cache_ttl_days: 7
      timeout_s: 60
      max_retries: 2

    judge_lead:
      primary: g_pro
      fallbacks: [g_flash, o_mini]
      mode: sync
      schema: LeadJudgement
      prompt: judge_lead.md
      max_output_tokens: 1200
      temperature: 0.2
      thinking: low
      tools: []
      priority: 2
      est_input_tokens: 5000
      est_output_tokens: 1000
      cache_ttl_days: 7
      timeout_s: 120
      max_retries: 2

    write_message:
      primary: o_mini
      fallbacks: [g_flash, g_pro]
      mode: sync
      schema: MessageDraft
      prompt: write_message.md
      max_output_tokens: 700
      temperature: 0.7
      thinking: low
      tools: []
      priority: 1
      est_input_tokens: 3000
      est_output_tokens: 500
      cache_ttl_days: 0
      timeout_s: 60
      max_retries: 2

    check_message:
      primary: g_flash
      fallbacks: [g_lite, o_mini]
      mode: sync
      schema: MessageCheck
      prompt: check_message.md
      max_output_tokens: 400
      temperature: 0.0
      thinking: low
      tools: []
      priority: 1
      est_input_tokens: 3000
      est_output_tokens: 300
      cache_ttl_days: 0
      timeout_s: 60
      max_retries: 2

    grounded_search:
      primary: g_flash
      fallbacks: [g_lite]                     # OpenAI web_search ($10 per 1K) is off by default; add o_mini to enable
      mode: sync
      schema: null                            # text + citations, structured by a second call (5.11)
      prompt: grounded_public_asks.md
      max_output_tokens: 1500
      temperature: 0.2
      thinking: low
      tools: [web_search]
      priority: 5
      est_input_tokens: 1000
      est_output_tokens: 500
      cache_ttl_days: 1
      timeout_s: 90
      max_retries: 2

    weekly_audit:
      primary: g_pro
      fallbacks: [g_flash, o_mini]
      mode: sync
      schema: AuditResult
      prompt: weekly_audit.md
      max_output_tokens: 1500
      temperature: 0.0
      thinking: medium
      tools: []
      priority: 6
      est_input_tokens: 6000
      est_output_tokens: 1000
      cache_ttl_days: 0
      timeout_s: 180
      max_retries: 2

  # Ready for later. Switch with settings.tier. Run `nlead eval` before switching.
  best:
    inherit: balanced
    overrides:
      extract_facts: { primary: g_pro, fallbacks: [g_flash, o_top] }
      verify_flagged: { primary: o_top, fallbacks: [g_pro, g_flash] }
      write_message: { primary: o_top, fallbacks: [g_pro, g_flash] }
      check_message: { primary: g_pro, fallbacks: [g_flash, o_mini] }
      classify_signal: { primary: g_flash, fallbacks: [g_lite, o_nano] }
  lean:
    inherit: balanced
    overrides:
      extract_facts: { primary: g_lite, fallbacks: [o_nano, g_flash] }
      judge_lead: { primary: g_flash, fallbacks: [g_lite, o_mini] }
      check_message: { primary: g_lite, fallbacks: [g_flash] }
      weekly_audit: { primary: g_flash, fallbacks: [g_lite] }
```

### 4.2.3 Loading and validation rules
1. Read `tiers[settings.tier]`. If the tier has `inherit`, start from the parent and apply `overrides` key by key.
2. Resolve short names (`g_flash`) into `{provider, model}` from the `models:` map.
3. Validate each task with a pydantic model `TaskConfig`. Fail at startup if anything is missing.
4. **Gemini-alone rule:** fail at startup if any chain has no Gemini entry.
5. Check every model in every chain has a price in `prices.yaml`.
6. Check every `schema` name exists in `nument_engine.models` and every `prompt` file exists.

```python
class ModelRef(BaseModel):
    provider: Literal["gemini", "openai"]
    model: str

class TaskConfig(BaseModel):
    name: str
    primary: ModelRef
    fallbacks: list[ModelRef]
    mode: Literal["sync", "batch"]
    schema_name: str | None = Field(alias="schema")
    prompt: str
    max_output_tokens: int
    temperature: float
    thinking: Literal["off", "low", "medium", "high"]
    tools: list[Literal["web_search"]]
    priority: int
    est_input_tokens: int
    est_output_tokens: int
    cache_ttl_days: int
    timeout_s: int
    max_retries: int

    @property
    def chain(self) -> list[ModelRef]:
        return [self.primary, *self.fallbacks]

    @model_validator(mode="after")
    def gemini_can_run_alone(self):
        if not any(m.provider == "gemini" for m in self.chain):
            raise ValueError(f"{self.name}: chain needs at least one gemini model")
        return self
```

---

## 4.3 Price table: `engine/config/prices.yaml`

Prices come from public trackers in Nov 2026. **Verify at build** on the official pricing pages and update `verified_on`.

```yaml
# engine/config/prices.yaml
verified_on: "2026-11-12"          # update when you re-check
sources:
  gemini: "https://ai.google.dev/gemini-api/docs/pricing"
  openai: "https://openai.com/api/pricing"
fx_inr_per_usd: 88                 # settings.fx_inr_per_usd overrides this if set

models:                            # USD per 1M tokens
  gemini-3.1-pro:        { input: 2.00, output: 12.00, batch_discount: 0.5 }   # thinking billed as output
  gemini-3-flash:        { input: 0.50, output: 3.00,  batch_discount: 0.5 }
  gemini-3.1-flash-lite: { input: 0.25, output: 1.50,  batch_discount: 0.5 }
  gpt-5.4:               { input: 2.50, output: 15.00, batch_discount: 0.5 }
  gpt-5-mini:            { input: 0.25, output: 2.00,  batch_discount: 0.5 }
  gpt-5-nano:            { input: 0.05, output: 0.40,  batch_discount: 0.5 }

tools:
  gemini_google_search:
    free_per_month: 5000           # shared across Gemini 3 and newer models
    usd_per_1000_after_free: 14.0
  openai_web_search:
    usd_per_1000_calls: 10.0       # plus search content tokens at the model input rate

apis:                               # logged with usd 0 while inside the free caps
  places_text_search_ids_only: { usd_per_1000: 0.0 }
  places_details_enterprise:  { usd_per_1000: 6.00, free_per_month_in: 7000, free_per_month_global: 1000 }
  places_details_atmosphere:  { usd_per_1000: 7.50, free_per_month_in: 7000, free_per_month_global: 1000 }
```

### 4.3.1 Cost formula
```
usd = (input_tokens / 1e6) * price.input + (output_tokens / 1e6) * price.output
if mode == batch: usd *= price.batch_discount
if gemini web_search: add (queries beyond the monthly free 5K) * 14 / 1000
if openai web_search: add calls * 10 / 1000
inr = usd * fx_inr_per_usd
```
Cached input tokens are billed at the provider's cached rate if known, otherwise at the full rate. Overestimating is the safe direction.

---

## 4.4 Verify model ids at build

Model names change every few months. Never guess them.

### 4.4.1 List Gemini models
```bash
$ cd engine
$ uv run python - <<'PY'
from google import genai
import os
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None)
    print(m.name, actions)
PY
```
Pick the current ids for the Pro, Flash and Flash-Lite models. Confirm each supports `generateContent`, that batch is available for Flash and Flash-Lite, and that the `google_search` tool works on Flash and Flash-Lite (the grounded_search chain uses both).

### 4.4.2 List OpenAI models (only if a key exists)
```bash
$ uv run python - <<'PY'
import os
from openai import OpenAI
if not os.environ.get("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY not set: OpenAI will be skipped, which is fine")
client = OpenAI()
for m in client.models.list():
    if m.id.startswith(("gpt-5", "gpt-6")):
        print(m.id)
PY
```

### 4.4.3 Startup check
`nlead health --models` loads `tasks.yaml`, lists the models of every **available** provider, and:
- fails if a configured **Gemini** model id is missing (Gemini must always work);
- warns (does not fail) if an OpenAI model id is missing or OpenAI is disabled or has no key.
```
FAIL  extract_facts primary gemini-3-flash not found. Closest: gemini-3-flash-preview-11-2026
WARN  write_message primary openai:gpt-5-mini skipped (providers_enabled.openai = false). Will use gemini:gemini-3-flash
```
Run it in CI (Step 17) and at the start of every night run (Step 14).

---

## 4.5 Provider availability and fallback (`llm/availability.py`)

### 4.5.1 Three reasons a provider is skipped
| Reason | How it is detected | Effect |
|---|---|---|
| Switched off | `settings.providers_enabled` (jsonb map, default `{"gemini": true, "openai": true}`), editable on the app's Engine page | Skipped for every task until switched on |
| No API key | `settings.gemini_api_key` / `settings.openai_api_key` empty at startup | Skipped; logged once per run as a warning |
| Circuit breaker open | Too many recent failures (4.5.2) | Skipped until the cool-off ends |

Defaults by environment:
- `APP_ENV=dev` (local and CI tests): `providers_enabled = {"gemini": true, "openai": false}`. **Local testing runs on Gemini only.**
- `APP_ENV=prod`: both enabled; the founder can switch OpenAI off any time.

### 4.5.2 Circuit breaker
One breaker per provider. State is kept in memory during a run and persisted in `source_health` under the names `llm:gemini` and `llm:openai`, so the next run respects a cool-off that is still active.

| Event | Breaker action |
|---|---|
| A call fails after its retries with a transient error (429, 5xx, timeout) | `failures += 1`. At 3 consecutive failures: **open** for 15 minutes |
| Auth, billing or quota-exhausted error (401, 403, "API key not valid", "billing", "insufficient_quota", "RESOURCE_EXHAUSTED" with a daily quota message) | **Open immediately** for 6 hours |
| A call succeeds | `failures = 0`, breaker **closed** |
| Cool-off ends | **Half-open:** the next call is a trial. Success closes it; failure opens it again with double the cool-off (max 24 hours) |

Persisted fields in `source_health` for `llm:<provider>`: `enabled` (mirrors `providers_enabled`), `last_ok_at`, `last_error_at`, `last_error`, `blocked_until` (cool-off end).

```python
# llm/availability.py
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from .. import db
from ..settings import settings

AUTH_HINTS = ("401", "403", "api key not valid", "permission", "billing", "insufficient_quota",
              "quota exceeded for quota metric", "account is not active")

@dataclass
class Breaker:
    provider: str
    failures: int = 0
    open_until: datetime | None = None
    cooloff: timedelta = timedelta(minutes=15)

    def is_open(self, now: datetime) -> bool:
        return self.open_until is not None and now < self.open_until

    def record_success(self):
        self.failures, self.open_until, self.cooloff = 0, None, timedelta(minutes=15)
        db.source_health_ok(f"llm:{self.provider}")

    def record_failure(self, err: Exception, now: datetime):
        msg = str(err).lower()
        if any(h in msg for h in AUTH_HINTS):
            self.open_until = now + timedelta(hours=6)
        else:
            self.failures += 1
            if self.failures >= 3:
                self.open_until = now + self.cooloff
                self.cooloff = min(self.cooloff * 2, timedelta(hours=24))
        db.source_health_error(f"llm:{self.provider}", str(err)[:500], blocked_until=self.open_until)

class Availability:
    def __init__(self):
        enabled = db.get_setting("providers_enabled") or {"gemini": True, "openai": settings.app_env == "prod"}
        keys = {"gemini": bool(settings.gemini_api_key), "openai": bool(settings.openai_api_key)}
        self.enabled = {p: bool(enabled.get(p, False)) and keys[p] for p in ("gemini", "openai")}
        self.breakers = {p: Breaker(p, open_until=db.source_health_blocked_until(f"llm:{p}"))
                         for p in ("gemini", "openai")}

    def usable(self, provider: str) -> bool:
        now = datetime.now(timezone.utc)
        return self.enabled.get(provider, False) and not self.breakers[provider].is_open(now)
```

### 4.5.3 Failover behaviour
1. The router walks `task.chain` in order and uses the first **usable** model.
2. If that call fails after its retries (or the output cannot be repaired into the schema), the breaker records the failure and the router tries the **next usable** model in the chain.
3. The cost row records the provider and model that actually answered, plus `fallback_from` (for example `openai:gpt-5-mini`) when it was not the primary.
4. For lead-level outputs (`write_message`, `judge_lead`), an `activities` row is written: `source = 'engine'`, `type = 'ai_output'`, `payload = {"task", "provider", "model", "fallback_from", "prompt_version"}`.
5. `runs.stats.fallbacks` counts fallbacks per task, shown on the app's Engine page.
6. If no usable model remains: raise `AllProvidersDown(task)`. The step skips the item and records it; the item is retried in the next run.

### 4.5.4 Quality when falling back
- Prompts are written provider-neutral. Every prompt is evaluated on its **primary and its first Gemini fallback** (Step 17).
- Gate: a fallback model must reach at least 90% of the primary's eval score. If it does not, reorder the chain or improve the prompt before go-live.
- Because Gemini must run everything alone, the go-live eval (Step 21) is run with `providers_enabled.openai = false`.

---

## 4.6 Gemini provider (`llm/gemini.py`)

### 4.6.1 Shared types (`llm/types.py`)
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

Provider = Literal["gemini", "openai"]

@dataclass
class LLMRequest:
    task: str
    provider: Provider
    model: str
    system: str                 # system part of the prompt file
    user: str                   # rendered user part of the prompt file
    schema: type | None         # pydantic model class or None
    max_output_tokens: int
    temperature: float
    thinking: str               # off | low | medium | high
    tools: list[str] = field(default_factory=list)
    timeout_s: int = 60
    key: str | None = None      # stable id for batch items, e.g. "extract_facts:<business_id>"

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0      # includes thinking / reasoning tokens
    cached_tokens: int = 0
    search_queries: int = 0     # gemini grounding queries or openai web_search calls

@dataclass
class LLMResponse:
    text: str
    parsed: Any | None
    usage: Usage
    provider: Provider
    model: str
    grounding: dict | None = None   # citations for web_search calls
    raw: Any | None = None
```

### 4.6.2 Sync calls with structured output
```python
# llm/gemini.py
from google import genai
from google.genai import types
from .types import LLMRequest, LLMResponse, Usage

THINKING = {"off": None, "low": "low", "medium": "medium", "high": "high"}

class GeminiProvider:
    name = "gemini"
    supports_batch = True

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def _config(self, req: LLMRequest) -> types.GenerateContentConfig:
        cfg: dict = {
            "system_instruction": req.system,
            "temperature": req.temperature,
            "max_output_tokens": req.max_output_tokens,
        }
        if req.schema is not None and "web_search" not in req.tools:
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = req.schema          # pydantic class is accepted by google-genai
        if THINKING[req.thinking]:
            # Gemini 3 takes a thinking level; Gemini 2.5 takes a token budget. Verify at build.
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING[req.thinking])
        if "web_search" in req.tools:
            cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        return types.GenerateContentConfig(**cfg)

    def generate(self, req: LLMRequest) -> LLMResponse:
        resp = self.client.models.generate_content(model=req.model, contents=req.user, config=self._config(req))
        um = resp.usage_metadata
        usage = Usage(
            input_tokens=(um.prompt_token_count or 0),
            output_tokens=(um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0),
            cached_tokens=(getattr(um, "cached_content_token_count", 0) or 0),
        )
        grounding = None
        cand = resp.candidates[0] if resp.candidates else None
        gm = getattr(cand, "grounding_metadata", None) if cand else None
        if gm:
            chunks = [{"uri": c.web.uri, "title": c.web.title}
                      for c in (gm.grounding_chunks or []) if getattr(c, "web", None)]
            queries = list(gm.web_search_queries or [])
            usage.search_queries = len(queries)
            grounding = {"queries": queries, "chunks": chunks,
                         "supports": [s.model_dump() for s in (gm.grounding_supports or [])]}
        return LLMResponse(text=resp.text or "", parsed=getattr(resp, "parsed", None), usage=usage,
                           provider="gemini", model=req.model, grounding=grounding, raw=resp)
```
Notes:
- Combining `google_search` with `response_schema` is not supported on every model. The router never combines them: web-search calls return text plus citations, and a second cheap call structures the text (5.11). Verify at build.
- Thinking tokens are billed as output. Keep `thinking: low` for extraction.

### 4.6.3 Batch calls (Gemini Batch API)
```python
    # inside GeminiProvider
    def submit_batch(self, model: str, reqs: list[LLMRequest], display_name: str) -> str:
        """Small batches inline; large batches through an uploaded JSONL file."""
        lines = [{"key": r.key, "request": {
                    "contents": [{"role": "user", "parts": [{"text": r.user}]}],
                    "system_instruction": {"parts": [{"text": r.system}]},
                    "generation_config": self._config(r).model_dump(exclude_none=True,
                                         exclude={"system_instruction", "tools"})}}
                 for r in reqs]
        if sum(len(json.dumps(l)) for l in lines) < 15_000_000:      # inline size limit, verify at build
            src = [{**l["request"], "metadata": {"key": l["key"]}} for l in lines]
            job = self.client.batches.create(model=model, src=src, config={"display_name": display_name})
        else:
            path = write_jsonl(lines)                                   # temp file
            up = self.client.files.upload(file=path, config={"mime_type": "jsonl", "display_name": display_name})
            job = self.client.batches.create(model=model, src=up.name, config={"display_name": display_name})
        return job.name                      # e.g. "batches/abc123"

    def poll_batch(self, name: str) -> str:
        return self.client.batches.get(name=name).state.name
        # JOB_STATE_PENDING | JOB_STATE_RUNNING | JOB_STATE_SUCCEEDED | JOB_STATE_FAILED | JOB_STATE_CANCELLED | JOB_STATE_EXPIRED

    def fetch_batch(self, name: str) -> list[tuple[str, LLMResponse | None, str | None]]:
        job = self.client.batches.get(name=name)
        rows = []
        if job.dest and job.dest.inlined_responses:
            for item in job.dest.inlined_responses:
                rows.append(((item.metadata or {}).get("key"), item.response, item.error))
        elif job.dest and job.dest.file_name:
            for line in self.client.files.download(file=job.dest.file_name).decode().splitlines():
                d = json.loads(line)
                rows.append((d.get("key"), d.get("response"), d.get("error")))
        out = []
        for key, r, err in rows:
            if err or r is None:
                out.append((key, None, str(err)))
                continue
            text, um = _text_and_usage(r)        # helper handles object or dict shapes
            out.append((key, LLMResponse(text=text, parsed=None, usage=um, provider="gemini", model=job.model), None))
        return out
```
Batch jobs usually finish in minutes to a few hours, with a 24 hour maximum. Verify the inline size limit and file limits at build.

---

## 4.7 OpenAI provider (`llm/openai_provider.py`)

### 4.7.1 Sync calls with strict JSON
```python
from openai import OpenAI
from .types import LLMRequest, LLMResponse, Usage

REASONING = {"off": None, "low": "low", "medium": "medium", "high": "high"}

class OpenAIProvider:
    name = "openai"
    supports_batch = True

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, timeout=120)

    def generate(self, req: LLMRequest) -> LLMResponse:
        kwargs: dict = {"model": req.model, "instructions": req.system, "input": req.user,
                        "max_output_tokens": req.max_output_tokens}
        if REASONING[req.thinking]:
            kwargs["reasoning"] = {"effort": REASONING[req.thinking]}
        else:
            kwargs["temperature"] = req.temperature      # some reasoning models ignore it; verify at build
        if "web_search" in req.tools:
            kwargs["tools"] = [{"type": "web_search"}]
        if req.schema is not None and "web_search" not in req.tools:
            resp = self.client.responses.parse(text_format=req.schema, **kwargs)
            parsed = resp.output_parsed
        else:
            resp = self.client.responses.create(**kwargs)
            parsed = None
        u = resp.usage
        usage = Usage(input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                      cached_tokens=getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0,
                      search_queries=sum(1 for o in resp.output if getattr(o, "type", "") == "web_search_call"))
        return LLMResponse(text=resp.output_text or "", parsed=parsed, usage=usage,
                           provider="openai", model=req.model, raw=resp)
```
Strict JSON schema rules for OpenAI: every property listed in `required`, `additionalProperties: false`, optional fields written as nullable (`str | None`). A helper `to_strict_schema(model)` produces this; it has its own unit test.

### 4.7.2 Batch calls (OpenAI Batch API)
```python
    def submit_batch(self, model: str, reqs: list[LLMRequest], display_name: str) -> str:
        path = write_jsonl([{"custom_id": r.key, "method": "POST", "url": "/v1/responses",
                             "body": {"model": model, "instructions": r.system, "input": r.user,
                                      "max_output_tokens": r.max_output_tokens,
                                      **({"text": {"format": {"type": "json_schema", "name": r.task,
                                                              "schema": to_strict_schema(r.schema), "strict": True}}}
                                         if r.schema else {})}} for r in reqs])
        up = self.client.files.create(file=open(path, "rb"), purpose="batch")
        b = self.client.batches.create(input_file_id=up.id, endpoint="/v1/responses",
                                       completion_window="24h", metadata={"display_name": display_name})
        return b.id

    def poll_batch(self, batch_id: str) -> str:
        return self.client.batches.retrieve(batch_id).status
        # validating | in_progress | finalizing | completed | failed | expired | cancelling | cancelled

    def fetch_batch(self, batch_id: str) -> list[tuple[str, LLMResponse | None, str | None]]:
        b = self.client.batches.retrieve(batch_id)
        out = []
        if b.output_file_id:
            for line in self.client.files.content(b.output_file_id).text.splitlines():
                row = json.loads(line)
                body = row["response"]["body"]
                text = "".join(c.get("text", "") for o in body.get("output", []) for c in (o.get("content") or []))
                u = body.get("usage", {})
                out.append((row["custom_id"], LLMResponse(text=text, parsed=None,
                            usage=Usage(u.get("input_tokens", 0), u.get("output_tokens", 0)),
                            provider="openai", model=body.get("model", "")), None))
        if b.error_file_id:
            for line in self.client.files.content(b.error_file_id).text.splitlines():
                row = json.loads(line)
                out.append((row["custom_id"], None, json.dumps(row.get("error") or row.get("response"))))
        return out
```

---

## 4.8 Output models (router-facing part of `models.py`)

All AI outputs are pydantic models. Keep them flat and strict-compatible (every field present, optional ones nullable). The full extraction model `ExtractedFacts` is defined in Step 9.

```python
from pydantic import BaseModel, Field
from typing import Literal

class SignalClassification(BaseModel):
    relevant: bool
    signal_type: Literal["hiring_builder", "hiring_frontdesk", "public_ask", "tender",
                         "review_pain", "new_branch", "news", "funding", "none"]
    employer_name: str | None
    employer_is_business_we_target: bool
    quote: str | None                       # exact words copied from the input
    confidence: float = Field(ge=0, le=1)

class NewsClassification(BaseModel):
    relevant: bool
    business_name: str | None
    city: str | None
    signal_type: Literal["new_branch", "news", "funding", "none"]
    quote: str | None
    confidence: float = Field(ge=0, le=1)

class PageChangeClassification(BaseModel):
    change_type: Literal["new_job", "new_branch", "removed", "cosmetic", "other"]
    roles: list[str]
    quote: str | None
    signal_type: Literal["hiring_builder", "hiring_frontdesk", "new_branch", "none"]

class PublicAskItem(BaseModel):
    poster_business: str | None
    poster_city: str | None
    need: str
    quote: str
    url: str
    posted_date: str | None

class PublicAskResults(BaseModel):
    items: list[PublicAskItem]

class FlaggedVerification(BaseModel):
    field: str
    resolved_value: str | None
    supported_by_quote: str | None
    verdict: Literal["confirmed", "contradicted", "unclear"]

class LeadJudgement(BaseModel):
    adjusted_grade: Literal["A", "B", "C", "D"]
    note: str                               # 2 short sentences, plain words
    best_angle: str
    risks: list[str]
    fact_ids_used: list[str]
    confidence: float = Field(ge=0, le=1)

class MessageDraft(BaseModel):
    message: str
    message_alt: str
    followup_d3: str
    followup_d7: str
    angle: str
    fact_ids_used: list[str]

class MessageCheck(BaseModel):
    score: int = Field(ge=0, le=10)
    problems: list[str]
    unsupported_claims: list[str]
    verdict: Literal["ship", "rewrite"]

class AuditResult(BaseModel):
    lead_id: str
    verdict: Literal["good", "weak", "wrong"]
    issues: list[str]
    should_have_grade: Literal["A", "B", "C", "D"]
```

---

## 4.9 Prompt loader with versions (`llm/prompts.py`)

### 4.9.1 Prompt file format
```markdown
---
task: extract_facts
version: 3
description: Pull facts from a business website, each with an exact quote and URL.
inputs: [business_name, segment_label, country, pages]
---
[system]
You extract facts about one business from its own web pages. ...

[user]
Business: {{ business_name }} ({{ segment_label }}, {{ country }})
{% for p in pages %}
=== PAGE {{ loop.index }}: {{ p.url }}
{{ p.text }}
{% endfor %}
```
Prompts are provider-neutral: no "As ChatGPT" or Gemini-specific wording. Output format instructions come from the schema, not from prose.

### 4.9.2 Loader
```python
import re, yaml
from pathlib import Path
from jinja2 import Environment, StrictUndefined

PROMPTS = Path(__file__).resolve().parents[3] / "prompts"
_env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)

class Prompt:
    def __init__(self, path: Path):
        raw = path.read_text()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        if not m:
            raise ValueError(f"{path.name}: missing front matter")
        self.meta = yaml.safe_load(m.group(1))
        sys_part, user_part = m.group(2).split("[user]", 1)
        self.system_tpl = _env.from_string(sys_part.replace("[system]", "", 1).strip())
        self.user_tpl = _env.from_string(user_part.strip())
        self.version = int(self.meta["version"])
        self.task = self.meta["task"]

    def render(self, **inputs) -> tuple[str, str]:
        missing = set(self.meta.get("inputs", [])) - set(inputs)
        if missing:
            raise KeyError(f"{self.task}: missing inputs {sorted(missing)}")
        return self.system_tpl.render(**inputs), self.user_tpl.render(**inputs)

def load(name: str) -> Prompt:
    return Prompt(PROMPTS / name)

def tag(provider: str, model: str, prompt: Prompt) -> str:
    """Stored in facts.model / leads.message_model / scores.judge_model,
    e.g. 'gemini:gemini-3-flash#extract_facts.v3'."""
    return f"{provider}:{model}#{prompt.task}.v{prompt.version}"
```

### 4.9.3 Versioning rules
1. Any wording change bumps `version` by 1.
2. Every stored AI output records `provider:model#task.vN`, so fallbacks are visible per row.
3. A prompt change must pass `nlead eval` on the golden subset (Step 17) on the primary **and** the first Gemini fallback before merging.

---

## 4.10 The router (`llm/router.py`)

```python
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception
from . import prompts
from .types import LLMRequest, LLMResponse
from .gemini import GeminiProvider
from .openai_provider import OpenAIProvider
from .availability import Availability
from ..budget import Budget, BudgetExceeded
from .. import db, models
from ..settings import settings

RETRYABLE = ("429", "500", "502", "503", "504", "timeout", "temporarily", "unavailable", "deadline")

class AllProvidersDown(Exception):
    pass

def _retryable(exc: Exception) -> bool:
    return any(k in str(exc).lower() for k in RETRYABLE)

class Router:
    def __init__(self, run_id: str, tasks: dict, prices: dict, max_spend_inr: float | None = None):
        self.run_id = run_id
        self.tasks = tasks
        self.prices = prices
        self.avail = Availability()
        self.providers = {}
        if settings.gemini_api_key:
            self.providers["gemini"] = GeminiProvider(settings.gemini_api_key)
        if settings.openai_api_key:
            self.providers["openai"] = OpenAIProvider(settings.openai_api_key)
        self.budget = Budget(prices=prices, run_id=run_id, max_spend_inr=max_spend_inr)

    # ---------------- public ----------------
    def run(self, task: str, inputs: dict, *, lead_id: str | None = None, cache_extra: str = ""):
        cfg = self.tasks[task]
        p = prompts.load(cfg.prompt)
        system, user = p.render(**inputs)
        key = hashlib.sha256("\x1f".join([task, str(p.version), system, user, cache_extra]).encode()).hexdigest()
        if cfg.cache_ttl_days and (hit := db.cache_get(key)):
            self._log_cost(task, "cache", "cache", 0, 0, 0.0, fallback_from=None)
            return self._validate(cfg, hit)

        last_err: Exception | None = None
        for i, ref in enumerate(cfg.chain):
            if ref.provider not in self.providers or not self.avail.usable(ref.provider):
                continue
            est = self.budget.estimate_inr(ref.model, cfg)
            self.budget.check(task=task, priority=cfg.priority, est_inr=est)   # raises BudgetExceeded
            req = LLMRequest(task=task, provider=ref.provider, model=ref.model, system=system, user=user,
                             schema=self._schema(cfg), max_output_tokens=cfg.max_output_tokens,
                             temperature=cfg.temperature, thinking=cfg.thinking, tools=cfg.tools,
                             timeout_s=cfg.timeout_s)
            fallback_from = None if i == 0 else f"{cfg.primary.provider}:{cfg.primary.model}"
            try:
                resp = self._call(req, cfg)
                result = self._parse_or_repair(cfg, req, resp, fallback_from)
            except BudgetExceeded:
                raise
            except Exception as e:
                last_err = e
                self.avail.breakers[ref.provider].record_failure(e, datetime.now(timezone.utc))
                db.bump_run_stat(self.run_id, f"fallbacks.{task}")
                continue
            self.avail.breakers[ref.provider].record_success()
            usd = self.budget.cost_usd(ref.model, resp.usage, batch=False,
                                       search_provider=ref.provider if "web_search" in cfg.tools else None)
            self._log_cost(task, ref.provider, ref.model, resp.usage.input_tokens,
                           resp.usage.output_tokens, usd, fallback_from=fallback_from,
                           search_queries=resp.usage.search_queries)
            if lead_id:
                db.insert("activities", {"lead_id": lead_id, "source": "engine", "type": "ai_output",
                                         "payload": {"task": task, "provider": ref.provider, "model": ref.model,
                                                     "fallback_from": fallback_from,
                                                     "prompt_version": p.version}})
            if cfg.cache_ttl_days:
                db.cache_put(key, task, ref.model, self._dump(result, resp), ttl_days=cfg.cache_ttl_days)
            return result
        raise AllProvidersDown(f"{task}: no usable provider in chain ({last_err})")

    # ---------------- internals ----------------
    def _call(self, req: LLMRequest, cfg) -> LLMResponse:
        @retry(stop=stop_after_attempt(cfg.max_retries + 1), wait=wait_exponential_jitter(initial=2, max=60),
               retry=retry_if_exception(_retryable), reraise=True)
        def _do():
            return self.providers[req.provider].generate(req)
        return _do()

    def _parse_or_repair(self, cfg, req, resp, fallback_from):
        schema = self._schema(cfg)
        if schema is None:
            return resp
        if resp.parsed is not None:
            return resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate(resp.parsed)
        try:
            return schema.model_validate_json(resp.text)
        except ValidationError as e:
            fix = LLMRequest(**{**req.__dict__, "user": req.user +
                                "\n\nYour last answer did not match the required JSON schema. "
                                f"Errors: {e.errors()[:5]}. Reply again with valid JSON only."})
            resp2 = self.providers[req.provider].generate(fix)
            usd = self.budget.cost_usd(req.model, resp2.usage, batch=False)
            self._log_cost(req.task, req.provider, req.model, resp2.usage.input_tokens,
                           resp2.usage.output_tokens, usd, fallback_from=fallback_from)
            return schema.model_validate_json(resp2.text)      # a second failure raises, triggering failover

    def _validate(self, cfg, data: dict):
        schema = self._schema(cfg)
        return schema.model_validate(data) if schema else data

    def _schema(self, cfg):
        return getattr(models, cfg.schema_name) if cfg.schema_name else None

    def _dump(self, result, resp) -> dict:
        return result.model_dump() if hasattr(result, "model_dump") else {"text": resp.text, "grounding": resp.grounding}

    def _log_cost(self, task, provider, model, inp, out, usd, fallback_from=None, search_queries=0):
        fx = self.budget.fx
        db.insert("costs", {"run_id": self.run_id, "provider": provider, "model": model, "task": task,
                            "input_tokens": inp, "output_tokens": out, "calls": 1,
                            "usd": round(usd, 6), "inr": round(usd * fx, 4), "fallback_from": fallback_from})
        if search_queries:
            db.insert("costs", {"run_id": self.run_id, "provider": provider, "model": model,
                                "task": f"{task}_queries", "input_tokens": 0, "output_tokens": 0,
                                "calls": search_queries, "usd": 0, "inr": 0, "fallback_from": fallback_from})
```

### 4.10.1 New database pieces (add in Step 2 migrations)
The contract (A.12) needs three small additions for this step:
```sql
-- AI answer cache
create table if not exists llm_cache (
  key text primary key,
  task text not null,
  model text not null,
  response jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index if not exists llm_cache_expires_idx on llm_cache (expires_at);

-- which provider was the planned one when a fallback answered
alter table costs add column if not exists fallback_from text;

-- provider switches (editable on the Engine page)
insert into settings (key, value) values
  ('providers_enabled', '{"gemini": true, "openai": true}'::jsonb)
on conflict (key) do nothing;
```
`db.cache_get(key)` returns a row only if `expires_at > now()`. The night run deletes expired rows.

### 4.10.2 Batch flow with provider fallback (`llm/batch.py`)
```
NIGHT (after research):
  items = businesses queued for extraction with pages ready
  ref = first model in extract_facts.chain whose provider is usable AND supports batch
        (if OpenAI is disabled, down or keyless, this is a Gemini model: Gemini Batch)
  budget.reserve(task, n_items * estimate_inr(ref.model))          # holds the money for the cap
  try:
      provider_batch_id = provider.submit_batch(ref.model, reqs, display_name=f"{run_id}:extract_facts")
  except error:
      breaker.record_failure(...)
      try the next batch-capable model in the chain
      if none: fall back to SYNC calls on the chain for up to 40 items (budget permitting),
               leave the rest queued for the next night
  insert llm_batches(provider, provider_batch_id, task, status='submitted', item_count=n, submitted_at=now())

MORNING (first thing):
  for each llm_batches row with status in ('submitted','running'):
      state = provider.poll_batch(id)          (poll every 60 s, at most 20 minutes in total)
      SUCCEEDED/completed: rows = provider.fetch_batch(id)
          parse each row with the task schema; invalid rows get one sync repair on the chain
          write facts (Step 9); write cost rows at batch prices (fallback_from set if not the primary)
          status='completed', completed_at=now(), release the reservation
      FAILED/EXPIRED/CANCELLED: status='failed'; items return to the queue for the next night;
          breaker.record_failure for that provider
      still running after 20 minutes: leave it; the next run collects it
```
Rules:
- Never submit the same `key` twice on the same day (checked against `llm_batches` and existing `facts`).
- If OpenAI batch is unavailable, the chain already moves to Gemini Batch. No code change is needed.

---

## 4.11 Budget guard (`budget.py`)

### 4.11.1 What it does
1. Today's spend: `select coalesce(sum(inr),0) from costs where at >= <today 00:00 IST>`.
2. Reserved spend: estimates for batches submitted today and not yet collected.
3. Before every call or batch: `spend + reserved + estimate` must stay under `settings.daily_cap_inr` (750).
4. **Per-run cap for local and test runs:** the global CLI flag `--max-spend-inr N` (for example `--max-spend-inr 20`). The run stops paid AI calls once that run's own spend reaches N. Unset in production. Tests always run with a small value (4.13).
5. At 80% (`settings.alert_pct`) of the daily cap it raises one alert per day (written to `runs.stats.alerts`, shown on the Engine page).
6. When a projection crosses a limit, it drops work by priority, lowest first.

### 4.11.2 Priority order (1 is never dropped)
| Priority | Tasks | Why |
|---|---|---|
| 1 | `write_message`, `check_message` for leads already graded A or B | Finishes work already paid for |
| 2 | `judge_lead` | Decides lead quality |
| 3 | `extract_facts`, `verify_flagged` | New research |
| 4 | `classify_signal`, `classify_page_change` | New signals |
| 5 | `grounded_search`, `classify_news` | Nice to have |
| 6 | `weekly_audit` | Can wait a day |

At 80% of the daily cap, priorities 5 and 6 stop for the day. At 95%, priority 4 stops. At the cap, only priority 1 continues, inside its own small reserve of ₹50. The per-run cap (`--max-spend-inr`) stops **all** paid calls for that run when reached.

### 4.11.3 Code
```python
from datetime import datetime, time
from zoneinfo import ZoneInfo
from . import db

IST = ZoneInfo("Asia/Kolkata")

class BudgetExceeded(Exception):
    pass

class Budget:
    def __init__(self, prices: dict, run_id: str, max_spend_inr: float | None = None):
        self.prices = prices
        self.run_id = run_id
        self.max_spend_inr = max_spend_inr
        s = db.get_settings()
        self.cap = float(s.get("daily_cap_inr", 750))
        self.alert_pct = float(s.get("alert_pct", 80)) / 100
        self.fx = float(s.get("fx_inr_per_usd", prices.get("fx_inr_per_usd", 88)))
        self.priority1_reserve = 50.0
        self._alerted = False

    def _today_start(self):
        now = datetime.now(IST)
        return datetime.combine(now.date(), time(0, 0), tzinfo=IST)

    def spent_today(self) -> float:
        return float(db.scalar("select coalesce(sum(inr),0) from costs where at >= %s", (self._today_start(),)))

    def spent_this_run(self) -> float:
        return float(db.scalar("select coalesce(sum(inr),0) from costs where run_id = %s", (self.run_id,)))

    def reserved(self) -> float:
        return float(db.scalar("""select coalesce(sum(reserved_inr),0) from llm_batch_reservations
                                  where released = false and created_at >= %s""", (self._today_start(),)))

    def cost_usd(self, model, usage, batch: bool, search_provider: str | None = None) -> float:
        p = self.prices["models"][model]
        usd = usage.input_tokens / 1e6 * p["input"] + usage.output_tokens / 1e6 * p["output"]
        if batch:
            usd *= p.get("batch_discount", 1.0)
        if search_provider == "gemini" and usage.search_queries:
            used = self.search_queries_this_month()
            free = self.prices["tools"]["gemini_google_search"]["free_per_month"]
            over = max(0, used + usage.search_queries - free) - max(0, used - free)
            usd += over * self.prices["tools"]["gemini_google_search"]["usd_per_1000_after_free"] / 1000
        if search_provider == "openai" and usage.search_queries:
            usd += usage.search_queries * self.prices["tools"]["openai_web_search"]["usd_per_1000_calls"] / 1000
        return usd

    def estimate_inr(self, model: str, cfg) -> float:
        p = self.prices["models"][model]
        usd = cfg.est_input_tokens / 1e6 * p["input"] + cfg.est_output_tokens / 1e6 * p["output"]
        if cfg.mode == "batch":
            usd *= p.get("batch_discount", 1.0)
        return usd * self.fx

    def search_queries_this_month(self) -> int:
        return int(db.scalar("""select coalesce(sum(calls),0) from costs
                                where task = 'grounded_search_queries' and provider = 'gemini'
                                and at >= date_trunc('month', now())"""))

    def check(self, task: str, priority: int, est_inr: float) -> None:
        if self.max_spend_inr is not None and self.spent_this_run() + est_inr > self.max_spend_inr:
            raise BudgetExceeded(f"{task}: run cap --max-spend-inr {self.max_spend_inr} reached")
        spent = self.spent_today() + self.reserved()
        used = spent / self.cap if self.cap else 1.0
        if used >= self.alert_pct and not self._alerted:
            db.add_run_alert(self.run_id, f"AI spend at {used:.0%} of the daily cap (₹{spent:.0f} of ₹{self.cap:.0f})")
            self._alerted = True
        if priority == 1:
            if spent + est_inr > self.cap + self.priority1_reserve:
                raise BudgetExceeded(f"{task}: cap and priority 1 reserve used")
            return
        if priority in (5, 6) and used >= 0.80:
            raise BudgetExceeded(f"{task}: paused at 80% of the daily cap")
        if priority == 4 and used >= 0.95:
            raise BudgetExceeded(f"{task}: paused at 95% of the daily cap")
        if spent + est_inr > self.cap:
            raise BudgetExceeded(f"{task}: would exceed the daily cap")
```
Batch reservations need one more small table (add in Step 2 migrations):
```sql
create table if not exists llm_batch_reservations (
  id bigserial primary key,
  llm_batch_id uuid references llm_batches(id) on delete cascade,
  reserved_inr numeric not null,
  released boolean not null default false,
  created_at timestamptz not null default now()
);
```

---

## 4.12 Smoke test and health
`nlead health --llm-smoke` sends one tiny request per task with fixed inputs, **on every usable provider in each chain**, and prints:
```
task             provider  model                  role      ok   in/out tokens  cost
classify_signal  gemini    gemini-3.1-flash-lite  primary   yes  412/61         ₹0.002
classify_signal  gemini    gemini-3-flash         fallback  yes  412/58         ₹0.004
judge_lead       gemini    gemini-3.1-pro         primary   yes  980/180        ₹0.36
judge_lead       gemini    gemini-3-flash         fallback  yes  980/170        ₹0.09
write_message    openai    gpt-5-mini             primary   skip (providers_enabled.openai = false)
write_message    gemini    gemini-3-flash         fallback  yes  760/150        ₹0.05
grounded_search  gemini    gemini-3-flash         primary   yes  210/300 q=2    ₹0.09
total                                                                           ₹0.9
```
- Default locally: Gemini only, because `APP_ENV=dev` sets `providers_enabled.openai = false`.
- `--providers gemini,openai` overrides it for a one-off check in prod.
- The smoke test always runs with `--max-spend-inr 5` built in, must cost under ₹5 and finish in under 3 minutes.

---

## 4.13 Tests (`test_llm_router.py`, `test_llm_fallback.py`, `test_budget.py`)

**All automated tests and local test runs use Gemini only.** Unit tests use fakes and never call real APIs. The live smoke test uses Gemini only unless told otherwise.

```python
class FakeProvider:
    def __init__(self, name, replies, supports_batch=True):
        self.name, self.replies, self.supports_batch = name, list(replies), supports_batch
        self.calls = []
    def generate(self, req):
        self.calls.append(req)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
```
Test cases:
1. **Happy path:** valid JSON parses into the schema; one `costs` row with the right USD and INR.
2. **Repair:** invalid JSON then valid JSON; two cost rows; result parses.
3. **Retry:** a `503` then success; two provider calls; one success cost row.
4. **No retry on 400:** a schema error is not retried by tenacity (only the single repair).
5. **Cache hit:** an identical second call reads `llm_cache`, logs a `cache` row with `usd = 0`, makes no provider call.
6. **Fallback, OpenAI disabled:** `providers_enabled.openai = false`; `write_message` is answered by `gemini:gemini-3-flash`; the cost row has `fallback_from = "openai:gpt-5-mini"`; an `activities` row records it.
7. **Fallback, OpenAI key missing:** same result as test 6 with `OPENAI_API_KEY` unset.
8. **Fallback on errors:** the primary raises `503` three times (after retries); the router moves to the next model; the breaker counts failures.
9. **Circuit breaker:** 3 consecutive failures open the breaker for 15 minutes (use a fake clock); calls skip that provider; after the cool-off a trial call closes it on success.
10. **Auth error:** a `401` opens the breaker immediately for 6 hours and is persisted in `source_health` as `llm:openai`.
11. **Chain exhausted:** every model fails; `AllProvidersDown` is raised; the run stat is recorded.
12. **Gemini-alone rule:** a `tasks.yaml` with a chain lacking Gemini fails validation.
13. **Batch fallback:** OpenAI disabled; `extract_facts` batch goes to Gemini Batch; if Gemini batch submit fails twice, up to 40 items run as sync calls and the rest stay queued.
14. **Budget:** at 79% a priority 5 task runs; at 81% it raises `BudgetExceeded`; at 100% a priority 1 task runs inside the ₹50 reserve; beyond that it raises.
15. **Per-run cap:** with `--max-spend-inr 5`, the call that would push the run past ₹5 raises `BudgetExceeded`, whatever the daily cap.
16. **Batch reserve:** a 300-item batch reserves its estimate; a second batch that would cross the cap is refused.
17. **Cost math:** batch discount halves cost; thinking tokens count as output; Gemini search queries beyond 5K per month are charged.
18. **Strict schema helper:** `to_strict_schema(LeadJudgement)` sets `additionalProperties: false` everywhere and lists every field in `required`.

Local test commands:
```bash
$ cd engine
$ APP_ENV=dev uv run pytest -q                                   # unit tests, no network
$ APP_ENV=dev uv run nlead health --models                       # Gemini models must exist
$ APP_ENV=dev uv run nlead health --llm-smoke --max-spend-inr 5  # Gemini only, under ₹5
$ APP_ENV=dev uv run nlead run night --segment clinics-in --limit 5 --dry-run --max-spend-inr 20
```

---

## 4.14 Pitfalls
- **Model ids drift.** Always verify at build (4.4) and run `nlead health --models` in CI.
- **Fallback quality differs.** Evaluate every prompt on its first Gemini fallback (4.5.4). A fallback that writes worse messages must not ship silently.
- **Thinking tokens cost money.** Gemini 3 and OpenAI reasoning models bill thinking as output. Keep `thinking: low` except for the weekly audit.
- **Schema features differ.** Gemini response schemas support a subset of JSON Schema (avoid `oneOf`, deep unions, regex). OpenAI strict mode needs every field required and `additionalProperties: false`. Keep models flat.
- **Batch is slow sometimes.** The morning run never waits more than 20 minutes for a batch.
- **Free tiers train on data.** Use paid keys only.
- **Prices change.** Update `prices.yaml` monthly (Step 22).
- **Search plus schema.** Never combine the search tool with a response schema unless verified for that model.
- **Breaker too eager.** A short outage should not switch everything to the fallback for hours. Only auth and billing errors get the 6 hour cool-off.

## 4.15 Done when
- [ ] `tasks.yaml` and `prices.yaml` load for the `balanced` tier; every chain contains a Gemini model; validation fails on a chain without one.
- [ ] `nlead health --models` passes for Gemini; OpenAI problems show as warnings only.
- [ ] With `providers_enabled.openai = false`, `nlead health --llm-smoke --max-spend-inr 5` runs **every task on Gemini** and costs under ₹5.
- [ ] With OpenAI enabled and a key present, `write_message` uses `gpt-5-mini`; with OpenAI disabled or keyless it uses `gemini-3-flash`, and the cost row shows `fallback_from`.
- [ ] Circuit breaker opens after 3 failures, persists in `source_health` (`llm:gemini`, `llm:openai`), and closes after a successful trial.
- [ ] Gemini Batch submit, poll and fetch work end to end with 3 test items; with OpenAI disabled, the extraction batch goes to Gemini Batch.
- [ ] Budget guard tests pass: 80%, 95%, cap, priority 1 reserve, batch reservation, and the `--max-spend-inr` per-run cap.
- [ ] `llm_cache`, `llm_batch_reservations`, `costs.fallback_from` and the `providers_enabled` setting exist (Step 2 migrations).
- [ ] Every stored AI output carries a `provider:model#task.vN` tag.
- [ ] All unit tests pass in CI with no network and no OpenAI key.

---

---

# Step 5: Source adapters

**Goal:** a set of small, well-behaved adapters, one per data source. Each adapter finds businesses or signals, follows the data rules in A.4, reports its own health, and can be switched off instantly.

**You need first:**
- Step 1 (package skeleton, `http.py` placeholder, `settings.py`).
- Step 2 (tables `source_records`, `businesses`, `signals`, `pages`, `source_health`, `settings`).
- Step 3 (segment YAML files: cities, bounding boxes, localities, categories, keywords).
- Step 4 (router for the classification tasks).
- `GOOGLE_MAPS_API_KEY` for `places.py` (the founder is setting it up). Every other adapter works without it.

**You will create:**
```
engine/src/nument_engine/http.py
engine/src/nument_engine/sources/base.py
engine/src/nument_engine/sources/overture.py
engine/src/nument_engine/sources/places.py
engine/src/nument_engine/sources/art_registry.py
engine/src/nument_engine/sources/practo.py
engine/src/nument_engine/sources/apna.py
engine/src/nument_engine/sources/careers_watch.py
engine/src/nument_engine/sources/gdelt.py
engine/src/nument_engine/sources/grounded_search.py
engine/src/nument_engine/sources/osm.py
engine/src/nument_engine/sources/adzuna.py
engine/tests/fixtures/sources/...          (saved HTML / JSON per adapter)
engine/tests/test_http.py
engine/tests/test_sources_*.py
```

---

## 5.1 Source classes and policies

Every adapter declares one policy. The policy sets its rate limit and how it reacts to blocks.

| Policy | Meaning | Default rate per host | robots.txt | On block |
|---|---|---|---|---|
| `official_api` | A documented API we have a key for (Places, Gemini grounding, Adzuna, GDELT API) | Provider limits, our own daily caps | not applicable | Back off, record error, stop for the run |
| `open_data` | Published open datasets (Overture on S3, ART registry page, OSM extracts) | 1 request per second | checked for web pages | Stop for the run |
| `public` | Public web pages that robots.txt allows (company websites, Practo profile pages) | 1 request per second (company sites), 1 per 5 seconds (directories) | **must allow** | Stop that host for the run |
| `grey` | Public pages whose terms ban robots, approved by the founder at a slow rate (Apna) | 1 request per 6 seconds | still checked; disallowed paths are never fetched | Stop the whole source, `blocked_until` 24 hours, then 72 hours, then 7 days |

Always:
- Honest User-Agent from `USER_AGENT` (`NumentLeadBot/1.0 (+https://nument.in)`).
- No login, no cookies from a logged-in session, no CAPTCHA solving, no proxies, no IP rotation, no fake app identities, no private APIs (A.4.2).
- Never fetch `linkedin.com`, `x.com`, `twitter.com`, `instagram.com` (hard block in `http.py`).

---

## 5.2 Polite HTTP layer (`http.py`)

Ported from the ideas in the old `lead-engine/scripts/check_links_emails.py` (`polite_get`, `robots_allows`, `classify`), rewritten as async with httpx.

### 5.2.1 Behaviour
1. **Never-fetch list:** hosts `linkedin.com`, `x.com`, `twitter.com`, `instagram.com`, `facebook.com`, `reddit.com`, `justdial.com`, `indiamart.com`, `sulekha.com` are refused before any network call.
2. **Per-host spacing:** an asyncio lock and a last-request time per host. The minimum gap comes from the adapter's policy, or from the site's `Crawl-delay` if that is larger.
3. **robots.txt:** fetched once per host per run and cached. Parsed with `urllib.robotparser` against our User-Agent. If robots.txt returns 401 or 403, treat every path as disallowed. If it is missing (404) or times out, treat as allowed (standard behaviour).
4. **Timeouts:** connect 10 seconds, read 20 seconds; total 30 seconds.
5. **Size cap:** stop reading after 6 MB (some site builders put content late in huge pages).
6. **Classification of every response** (`classify`):

| Condition | Result |
|---|---|
| TLS verification failure | `unknown` (not dead; local interception is common) |
| Timeout, reset, temporary failure | `unknown` (retry next run) |
| DNS failure | `broken` |
| 200 to 399 | `ok` |
| 401, 403, 429, 503, or page text contains "captcha", "cloudflare", "access denied", "are you a robot" | `blocked` |
| Other 4xx and 5xx | `broken` |

7. **Block handling:** a `blocked` result raises `SourceBlocked(source, host)`. The adapter catches it, writes `source_health.last_error` and `blocked_until`, and stops (per policy in 5.1). It never retries a blocked host in the same run.
8. **Request counting:** every request increments `source_health.requests_today` (reset nightly).

### 5.2.2 Code skeleton
```python
# http.py
import asyncio, time, urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from .settings import settings

NEVER = ("linkedin.com", "x.com", "twitter.com", "instagram.com", "facebook.com", "reddit.com",
         "justdial.com", "indiamart.com", "sulekha.com")
BLOCK_HINTS = ("captcha", "cloudflare", "access denied", "are you a robot", "unusual traffic")
MAX_BYTES = 6_000_000

class SourceBlocked(Exception):
    def __init__(self, source: str, host: str, reason: str):
        super().__init__(f"{source} blocked at {host}: {reason}")
        self.source, self.host, self.reason = source, host, reason

class NeverFetch(Exception):
    pass

@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    text: str
    state: str            # ok | blocked | broken | unknown | robots_skip
    reason: str = ""

def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h

class PoliteClient:
    def __init__(self, source: str, min_gap_s: float):
        self.source, self.min_gap = source, min_gap_s
        self.client = httpx.AsyncClient(headers={"User-Agent": settings.user_agent,
                                                 "Accept": "text/html,application/json,*/*"},
                                        timeout=httpx.Timeout(30, connect=10), follow_redirects=True,
                                        http2=True)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def _wait(self, host: str, gap: float):
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delta = gap - (time.monotonic() - self._last.get(host, 0))
            if delta > 0:
                await asyncio.sleep(delta)
            self._last[host] = time.monotonic()

    async def robots_allows(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = await self.client.get(base + "/robots.txt")
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp.allow_all = True
            self._robots[base] = rp
        return rp.can_fetch(settings.user_agent, url)

    def crawl_delay(self, url: str) -> float:
        p = urlparse(url)
        rp = self._robots.get(f"{p.scheme}://{p.netloc}")
        d = rp.crawl_delay(settings.user_agent) if rp else None
        return float(d or 0)

    async def get(self, url: str, *, check_robots: bool = True) -> FetchResult:
        host = host_of(url)
        if any(host == n or host.endswith("." + n) for n in NEVER):
            raise NeverFetch(url)
        if check_robots and not await self.robots_allows(url):
            return FetchResult(url, url, None, "", "robots_skip", "disallowed by robots.txt")
        await self._wait(host, max(self.min_gap, self.crawl_delay(url)))
        try:
            async with self.client.stream("GET", url) as r:
                chunks, size = [], 0
                async for c in r.aiter_bytes():
                    chunks.append(c); size += len(c)
                    if size > MAX_BYTES:
                        break
                body = b"".join(chunks).decode(r.encoding or "utf-8", "replace")
                state, reason = classify(r.status_code, body, None)
                res = FetchResult(url, str(r.url), r.status_code, body, state, reason)
        except httpx.HTTPError as e:
            state, reason = classify(None, "", e)
            res = FetchResult(url, url, None, "", state, reason)
        if res.state == "blocked":
            raise SourceBlocked(self.source, host, res.reason)
        return res

def classify(status, body, err) -> tuple[str, str]:
    if err is not None:
        msg = str(err).lower()
        if "certificate" in msg:
            return "unknown", "TLS verification failed"
        if isinstance(err, (httpx.TimeoutException, httpx.RemoteProtocolError)) or "reset" in msg:
            return "unknown", f"network: {msg[:80]}"
        return "broken", msg[:120]
    if status in (401, 403, 429, 503) or any(h in body[:5000].lower() for h in BLOCK_HINTS):
        return "blocked", f"{status}"
    if 200 <= status < 400:
        return "ok", str(status)
    return "broken", str(status)
```

---

## 5.3 Base adapter (`sources/base.py`)

### 5.3.1 The common record
```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class SourceRecord:
    source: str                     # adapter name, e.g. "overture"
    source_key: str                 # stable id inside that source
    segment_id: str
    name: str | None = None
    website: str | None = None
    phones_raw: list[str] = field(default_factory=list)   # only if the business published them in this source
    emails: list[str] = field(default_factory=list)
    address: str | None = None
    city: str | None = None
    locality: str | None = None
    lat: float | None = None
    lng: float | None = None
    category: str | None = None
    subcategory: str | None = None
    place_id: str | None = None
    overture_id: str | None = None
    observed_at: datetime | None = None
    payload: dict = field(default_factory=dict)            # raw fields we are allowed to keep
```

### 5.3.2 The adapter contract
```python
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from .. import db
from ..http import PoliteClient, SourceBlocked

BACKOFF = [timedelta(hours=24), timedelta(hours=72), timedelta(days=7)]

class SourceAdapter(ABC):
    name: str
    policy: str                     # official_api | open_data | public | grey
    min_gap_s: float = 1.0

    def __init__(self, ctx):
        self.ctx = ctx                                      # run_id, router, settings, dry_run, limit
        self.http = PoliteClient(self.name, self.min_gap_s)

    # ---------- switches ----------
    def enabled(self) -> bool:
        flags = db.get_setting("sources_enabled") or {}
        if flags.get(self.name) is False:
            return False
        blocked_until = db.source_health_blocked_until(self.name)
        return not (blocked_until and blocked_until > datetime.now(timezone.utc))

    # ---------- what adapters may implement ----------
    async def discover(self, segment) -> list[SourceRecord]:      # new businesses for the universe
        return []
    async def signals(self, segment) -> list[dict]:                # new signal rows
        return []
    async def enrich(self, business) -> dict:                      # extra facts for one business
        return {}

    # ---------- shared helpers ----------
    def save_records(self, recs: list[SourceRecord]) -> int:
        if self.ctx.dry_run:
            return len(recs)
        return db.upsert_source_records(recs)        # unique (source, source_key); updates payload, fetched_at

    def health_ok(self):
        db.source_health_ok(self.name)

    def health_blocked(self, err: SourceBlocked):
        prior = db.source_health_block_count(self.name)            # blocks in the last 30 days
        until = datetime.now(timezone.utc) + BACKOFF[min(prior, len(BACKOFF) - 1)]
        db.source_health_error(self.name, str(err), blocked_until=until)
```

### 5.3.3 How the pipeline uses adapters
- Step 6 (universe) calls `discover()` on Overture, Places, ART registry, OSM.
- Step 7 (signals) calls `signals()` on Apna, careers watch, GDELT, grounded search, Places reviews, Overture monthly diff, Adzuna.
- Step 9 (research) calls `enrich()` on Practo and Places details.
- Each call is wrapped:
```python
async def safe_call(adapter, fn, *args):
    if not adapter.enabled():
        return []
    try:
        out = await fn(*args)
        adapter.health_ok()
        return out
    except SourceBlocked as e:
        adapter.health_blocked(e)
        db.add_run_alert(adapter.ctx.run_id, f"{adapter.name} blocked: {e.reason}")
        return []
```

---

## 5.4 `overture.py`: the free world map of businesses

**Purpose:** the main universe source for every segment and country. Free open data (CDLA Permissive 2.0 / Apache 2.0). Also gives the monthly **new place** signal.

### 5.4.1 Finding the latest release
- STAC catalog: `https://stac.overturemaps.org/catalog.json` lists releases. The latest at the time of writing is `2026-10-21.0`. **Verify at build.**
- S3 keeps only about two releases, so always read the release id from the catalog, never hardcode it in code (keep it in `settings.overture_release`, updated by the monthly job).
- Places path: `s3://overturemaps-us-west-2/release/<release>/theme=places/type=place/*`.

### 5.4.2 Categories
The old `categories` field was removed in Sep 2026. Use `taxonomy.primary` and `taxonomy.hierarchy`. Codes come from the taxonomy file for the release (`https://labs.overturemaps.org/web-tools/taxonomy-explorer/taxonomy/<release>/taxonomy.csv`). Each segment YAML (Step 3) lists its codes, for example clinics: `dental_clinic`, `dermatology`, `aesthetic_medicine`, `fertility_clinic`, `psychology`, `psychotherapy`, `counseling`, `behavioral_or_mental_health_clinic`, `hair_loss_center`. Real estate and education codes must be looked up in the taxonomy file at build.

### 5.4.3 Query (DuckDB)
```python
import duckdb

SQL = """
INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';
SELECT id,
       names.primary                 AS name,
       taxonomy.primary              AS category,
       taxonomy.hierarchy            AS hierarchy,
       websites, phones, emails, socials,
       addresses[1].freeform         AS address,
       addresses[1].locality         AS locality,
       confidence, operating_status,
       ST_Y(geometry) AS lat, ST_X(geometry) AS lng
FROM read_parquet('s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*',
                  hive_partitioning=1)
WHERE bbox.xmin BETWEEN {minx} AND {maxx}
  AND bbox.ymin BETWEEN {miny} AND {maxy}
  AND list_has_any(taxonomy.hierarchy, {codes})
  AND coalesce(operating_status, 'open') = 'open'
  AND confidence >= {min_conf}
"""

def query_city(release: str, bbox: dict, codes: list[str], min_conf: float = 0.5):
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    q = SQL.format(release=release, minx=bbox["minx"], maxx=bbox["maxx"], miny=bbox["miny"],
                   maxy=bbox["maxy"], codes=codes, min_conf=min_conf)
    return con.execute(q).fetch_arrow_table().to_pylist()
```
Notes:
- The bounding box filter on `bbox.*` columns lets DuckDB skip most files (predicate pushdown). One metro takes about 1 to 3 minutes on a GitHub runner. **Verify at build.**
- Column names and nesting (`addresses`, `names`) must be checked against the release schema docs. **Verify at build.**
- Alternative: `overturemaps download --bbox=73.70,18.40,74.05,18.70 -f geoparquet --type=place -o pune.parquet`, then filter locally.

### 5.4.4 Mapping to `SourceRecord`
| Overture field | SourceRecord field | Rule |
|---|---|---|
| `id` | `source_key`, `overture_id` | stable across releases (GERS id) |
| `names.primary` | `name` | |
| `taxonomy.primary` | `category` / `subcategory` | mapped by the segment's category table |
| `websites[0]` | `website` | skip social and aggregator hosts (facebook, instagram, practo, justdial) |
| `phones` | `phones_raw` | used **only as a hint** to find the phone on the business's own site; never stored as the contact phone by itself (A.4.3) |
| `emails` | `emails` | business emails only |
| address fields | `address`, `locality`, `city` | city comes from the segment city whose bbox matched |
| geometry | `lat`, `lng` | |
| `confidence`, `operating_status`, `socials` | `payload` | kept for scoring and dedupe |
| release id | `payload.release` | used for the monthly diff |

### 5.4.5 Monthly diff: the `new_place` signal
1. The monthly job (Step 14 `monthly.yml`) reads the new release id from STAC.
2. For each segment city it queries ids only (cheap) for both the new and previous release.
3. Ids present in the new release and absent in the previous one are **added places**. (Overture also publishes a GERS changelog with `added` entries: use it if available, it is cheaper. **Verify at build.**)
4. For each added place with `confidence >= 0.7` and a matching category: create the business (Step 6) and a `new_place` signal: `points = 5`, `expires_at = observed_at + 60 days`, `url = null`, `quote = null`, `details = {"release": new, "confidence": c}`, `dedupe_key = "new_place:" + overture_id`.

### 5.4.6 Limits and pitfalls
- Overture India coverage is unknown until measured. **Week 1 data check:** run Pune for all clinic codes and report counts with website and phone fill rates (Step 24 week 1).
- Some places are duplicates of each other or stale. Entity resolution (Step 6) and verification (Step 10) handle that.
- Never hardcode the release path in tests. Use a small saved parquet fixture (20 rows).

---

## 5.5 `places.py`: Google Places API (New)

**Purpose:** fills the gaps Overture leaves, and gives the **can-pay proxies** (rating, review count) and the review-based pain signal. Official API, key required.

### 5.5.1 Three call types and their SKUs (India pricing, verify at build)
| Call | Endpoint | Field mask | SKU / price | Free per month (India) |
|---|---|---|---|---|
| Find ids | `POST https://places.googleapis.com/v1/places:searchText` | `places.id,nextPageToken` | Text Search Essentials (IDs only) | unlimited, free |
| Details | `GET https://places.googleapis.com/v1/places/{place_id}` | `id,displayName,formattedAddress,location,rating,userRatingCount,websiteUri,nationalPhoneNumber,internationalPhoneNumber,businessStatus,primaryType,types` | Place Details Enterprise, $6.00 per 1K | 7,000 |
| Reviews | same endpoint | `id,reviews` | Place Details Enterprise + Atmosphere, $7.50 per 1K | 7,000 |

Outside India the free allowance is about 1,000 per month per SKU (verify at build), so the daily caps are lower (A.10.2).

### 5.5.2 Find ids (free)
```python
SEARCH = "https://places.googleapis.com/v1/places:searchText"

async def search_ids(self, text_query: str, region: str, rect: dict) -> list[str]:
    ids, token = [], None
    for _ in range(3):                                # at most 60 results per query
        body = {"textQuery": text_query, "pageSize": 20, "regionCode": region, "languageCode": "en",
                "locationRestriction": {"rectangle": rect}}
        if token:
            body["pageToken"] = token
        r = await self.api.post(SEARCH, json=body, headers={
            "X-Goog-Api-Key": settings.google_maps_api_key,
            "X-Goog-FieldMask": "places.id,nextPageToken"})
        r.raise_for_status()
        data = r.json()
        ids += [p["id"] for p in data.get("places", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids
```
- Query plan per segment city: for each locality in the segment YAML and each query term (for example "dermatology clinic", "IVF centre", "real estate developer office"), build `"<term> in <locality>, <city>"`. This beats the 60-result cap per query.
- Throttle 5 requests per second. Log each call as a `costs` row with `provider = "google"`, `task = "places_search_ids"`, `usd = 0` so usage is visible.

### 5.5.3 Details (paid beyond the free caps)
```python
DETAILS_MASK = ("id,displayName,formattedAddress,location,rating,userRatingCount,websiteUri,"
                "nationalPhoneNumber,internationalPhoneNumber,businessStatus,primaryType,types")

async def details(self, place_id: str) -> dict:
    if not self.quota.take("places_details", self.daily_cap("details")):
        raise QuotaReached("places_details")
    r = await self.api.get(f"https://places.googleapis.com/v1/places/{place_id}",
                           headers={"X-Goog-Api-Key": settings.google_maps_api_key,
                                    "X-Goog-FieldMask": DETAILS_MASK})
    r.raise_for_status()
    return r.json()
```
Rules:
- Call details only for ids not seen before, or seen more than 30 days ago (`businesses.places_fetched_at`).
- Daily caps: India 230 per SKU per day; abroad 30 per SKU per day (settings keys `places_details_cap_in`, `places_details_cap_global`). Also set the same caps as **quotas in the Google Cloud console** so Google enforces them too.
- `businessStatus` other than `OPERATIONAL` marks the business `dormant`.

### 5.5.4 Reviews (pain signal) only for the shortlist
- Called only for businesses that passed the pre-filter (Step 8) and are about to be researched.
- The 5 most relevant reviews are sent to `classify_signal` with the prompt asking: do these reviews mention unanswered calls, slow replies, missed appointments, booking trouble, rude or absent front desk?
- If yes: create a `review_pain` signal with `points = 6` (more if 2+ reviews mention it, capped at 7), `expires_at = now + 90 days`, `url = "https://www.google.com/maps/place/?q=place_id:<id>"`, **`quote = null`** and `details = {"mentions": n, "themes": ["calls not answered", ...]}`.
- **Never store review text** (Google terms). The message writer may say "noticed a few reviews mention calls not getting picked up", which is our own summary.

### 5.5.5 Storage rules (Google terms)
| Data | May we store it? | How |
|---|---|---|
| `place_id` | Yes, permanently | `businesses.place_id` |
| lat/lng | Up to 30 days | `businesses.lat/lng`, refreshed by the monthly job |
| rating, review count, website, phone, name, address | Use for scoring; refresh at least every 30 days | `businesses.rating`, `review_count`, `places_fetched_at`; a nightly cleanup nulls these 30 days after `places_fetched_at` unless refreshed |
| Review text | **Never** | derived signal only |

Phones from Places are used only as the "Google listing" fallback contact (A.4.3), stored in `contacts` with `source = 'google_listing'`, and re-fetched within 30 days.

### 5.5.6 Errors
| Error | Meaning | Action |
|---|---|---|
| 403 `PERMISSION_DENIED`, API not enabled | Key or API setup missing | Stop adapter, alert, `places` disabled until fixed |
| 429 or `RESOURCE_EXHAUSTED` | Quota reached | Stop for the day |
| 400 `INVALID_ARGUMENT` | Bad field mask or body | Bug: fail the test suite |

---

## 5.6 `art_registry.py`: India IVF clinic registry

**Purpose:** a complete official list of registered ART (IVF) clinics in India, for the `clinics-in` segment, subcategory IVF.

- URL: `https://registry.artsurrogacy.gov.in/clinic/list?type=register-clinic`. One public HTML page, no login, no CAPTCHA (checked 12 Nov 2026). 4,767 rows at that time.
- Policy: `open_data`, 1 request, monthly.
- Parse the table with selectolax: name, address, state, email, registration number, certificate PDF link. Emails are written like `name[at]domain[dot]com`; decode `[at]` to `@` and `[dot]` to `.`.
- City mapping: match address text against each segment city's names and aliases (for example "Gurugram", "Gurgaon"; "Navi Mumbai", "Thane" into Mumbai metro). Rows outside target cities are skipped.
- Output `SourceRecord`: `source = "art_registry"`, `source_key = registration number`, `category = "clinic"`, `subcategory = "ivf"`, email in `emails`, no phone (the registry has none).
- These records usually lack a website. Step 6 resolves them against Overture and Places by name and city, and the research step finds the website.
- The certificate PDF link and registration number go into `payload` (proof the clinic is legitimate).

---

## 5.7 `practo.py`: clinic size and price signals (India)

**Purpose:** enrichment for clinics in India: number of doctors, consultation fee, "profile is claimed", rating. These are strong **can-pay proxies**. Not used for discovery.

- Policy: `public`, 1 request per 5 seconds. **Off by default** (`sources_enabled.practo = false`) until the founder reads Practo's terms and switches it on.
- robots.txt (checked 12 Nov 2026): search pages (`/search*`, `?q=`), appointment pages and APIs are disallowed; clinic and doctor profile pages are allowed and listed in sitemaps. The code re-checks robots.txt for every URL anyway.
- Finding the clinic's profile URL: read sitemap URLs from `https://www.practo.com/robots.txt` (`Sitemap:` lines), download the clinic sitemaps for target cities monthly, and keep a list of clinic profile URLs (`/<city>/clinic/<slug>`). Match a business to a URL by fuzzy name (rapidfuzz `token_set_ratio >= 90`) plus locality in the slug or page.
- Parse from the profile page:
  - "Profile is claimed" text, then `practo_claimed = true`
  - rating and number of patient stories
  - "Doctors (N)", then `practo_doctors = N`
  - consultation fees, then `practo_fee_min`, `practo_fee_max`
- Write each as a `facts` row with the exact quote and the page URL (verified later by quote check, Step 10).
- No phone numbers: Practo shows masked or virtual numbers, which are not the clinic's own.

---

## 5.8 `apna.py`: hiring signals (India, grey)

**Purpose:** businesses hiring receptionists, telecallers, patient coordinators, admissions counsellors, front-desk or sales staff. That is the `hiring_frontdesk` signal (visible pain), and some builder roles (`hiring_builder`).

- Policy: **`grey`**. Apna's terms ban robots and spiders, but robots.txt allows the pages and the founder approved slow grey scraping. Rate: 1 request per 6 seconds, at most 300 job pages per day, stop the whole source on any block.
- Discovery: sitemap index `https://apna.co/api/sitemap-index.xml` lists job sitemaps. Job URL pattern: `apna.co/job/<city>/<title-slug>-<id>`. About 26,600 active jobs on 12 Nov 2026. In the 5 metros: receptionist or front desk 188, telecaller 732, patient coordinator or counsellor 102, clinic, dental or hospital 113.
- Filter URLs **before fetching**, using the city slug and title keywords from each segment's YAML, for example:
  - clinics: receptionist, front desk, front office, patient coordinator, clinic coordinator, telecaller, customer care
  - real estate: telecaller, sales executive, tele sales, pre-sales, site visit
  - education: counsellor, admissions, telecaller, academic coordinator
- Fetch each job page. Parse JSON-LD `JobPosting` first (extruct): `title`, `hiringOrganization.name`, `datePosted`, `jobLocation`, `baseSalary`. Fall back to HTML parsing.
- Classify with `classify_signal`: is the employer a business in our target domains (not a staffing agency or BPO), which signal type.
- Match the employer to a business (Step 6, name plus city). If none matches, create a candidate business with `source = "apna"`, no phone.
- Never store recruiter names or personal phone numbers shown on job pages. They are not business-published contacts.
- Signal row: `type = hiring_frontdesk` (or `hiring_builder`), `points = 8`, `expires_at = datePosted + 30 days`, `url = job page`, `quote = job title + one line from the description`, `dedupe_key = "apna:" + job_id`.

---

## 5.9 `careers_watch.py`: hiring and new-branch signals from company websites

**Purpose:** watch the careers and locations pages of businesses we already know, and turn changes into signals. Works in every country.

- Policy: `public`, 1 request per host per second, robots.txt respected.
- Which pages: during research (Step 9), any page classified as careers, jobs, join us, locations, branches or clinics is stored in `pages` with its `text_hash`. These become watch targets for businesses with status `researched` or `qualified`, and for leads in open stages.
- Nightly: re-fetch each watch target (at most 1 page per host per night). If `text_hash` changed:
  1. Compute the added lines (difflib on normalized text).
  2. Send the added text to `classify_page_change`.
  3. `new_job` with front-desk roles creates `hiring_frontdesk`; builder roles create `hiring_builder`; `new_branch` creates `new_branch` (points 5, 60 days). The quote is taken from the added lines and verified in the stored text.
  4. Update `pages.text`, `text_hash`, `fetched_at`.
- No always-on watcher service is needed. This runs inside the night job (GitHub Actions has no persistent server).
- Budget: at most 400 watch fetches per night, oldest checked first.

---

## 5.10 `gdelt.py`: news signals

**Purpose:** news about openings, new branches, launches, expansion, funding, in every country.

- Policy: `official_api` (free; commercial use allowed with credit to GDELT). Rate: 1 request per 5 seconds.
- Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc` with parameters:
  - `query`: from the segment YAML, for example `("new clinic" OR "opens" OR "launches" OR "new branch") (dermatology OR IVF OR "skin clinic") sourcecountry:IN`
  - `mode=ArtList`, `format=json`, `maxrecords=250`, `timespan=1d`, `sort=DateDesc`
- Parse each article: `url`, `title`, `seendate`, `domain`, `language`, `sourcecountry`.
- Fetch the article page politely (robots respected) and extract main text with trafilatura (first 3,000 characters).
- Classify with `classify_news`: is it about a business in our domains and cities, which business, which signal (`new_branch`, `news`, `funding`).
- Match the business by fuzzy name plus city (Step 6). If not found, create a candidate.
- Signals: `new_branch` (5 points, 60 days), `news` (3 points, 30 days), `funding` (0 intent points, +6 can-pay, 120 days). The quote must be found in the article text (code check).

---

## 5.11 `grounded_search.py`: public asks and decision makers

**Purpose:** find **public asks** ("looking for a developer to build a WhatsApp bot for my clinic"), the strongest stated-need signal, and look up decision makers for qualified leads. Uses Gemini's Google Search grounding (5,000 free queries per month).

### 5.11.1 Two-call pattern
1. **Search call** (`grounded_search` task, web_search tool on): a prompt per segment asks for recent public posts where a business in that domain and country asks for a developer, agency, chatbot, automation, CRM or website, with the poster, the ask, the date and the link. Output is text plus grounding citations (`grounding.chunks` with `uri` and `title`).
2. **Structure call** (`classify_signal` task or a small structuring prompt with the `PublicAskResults` schema): turns the text into `PublicAskItem` rows. Each item must point at a cited URL from the grounding metadata; items without a citation are dropped.

### 5.11.2 Evidence rules
- If the cited URL is a normal web page (a forum, a company site, a news site): fetch it politely and **verify the quote** in the page text. Verified items create a `public_ask` signal: 10 points, 14 days.
- If the cited URL is LinkedIn or X (never fetched, A.4.2): keep the search snippet as the quote, mark `details.snippet_only = true`, use 6 points instead of 10, and show "snippet only, check before sending" in the app.
- The poster must be a business (or its owner) in a target domain. Individuals asking for personal projects are dropped.

### 5.11.3 Budget
- At most 160 search queries per day (5K per month), shared with decision-maker lookups.
- Queries are rotated across segments so each segment gets searched at least twice a week.
- Each query's count is logged as a `grounded_search_queries` cost row (Step 4.11).

### 5.11.4 Decision-maker lookups
For leads graded A or B with no decision maker found on the website: one grounded query `"<business name>" <city> founder OR owner OR director`. A name is accepted only if the cited page is the business's own site, a news article, or a registry, and the quote contains the name and role. LinkedIn snippets may supply a name only with `snippet_only = true`, and never a phone number.

---

## 5.12 `osm.py`: OpenStreetMap gaps

**Purpose:** fill gaps where Overture and Places are thin. Low trust.

- Policy: `open_data`. Preferred: monthly offline read of the Geofabrik India (and GCC) extract with `quackosm`, filtered by the segment bboxes and tags. No load on public servers.
- Online alternative for small checks: Overpass API `https://overpass-api.de/api/interpreter`, at most 1 request per 10 seconds, small bboxes only (Overpass usage policy: about 10K requests per day per user, keep far below).
- Tags by domain (examples): clinics `healthcare=*`, `amenity=dentist`, `amenity=clinic`, `amenity=doctors`; real estate `office=estate_agent`; education `amenity=school`, `amenity=college`, `office=educational_institution`.
- Measured on 12 Nov 2026 for Pune: 92 dentists and 482 clinics in OSM, thin compared with reality. Use OSM only to add businesses that no other source has.
- `SourceRecord`: `source = "osm"`, `source_key = "node/<id>"` or `"way/<id>"`, website and phone tags as hints only.

---

## 5.13 `adzuna.py`: official job API (optional)

**Purpose:** an official, rule-compliant job feed where coverage exists. Optional.

- Policy: `official_api`. Needs a free `app_id` and `app_key`, created by the founder on Adzuna's developer site (we never create accounts).
- Endpoint: `https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id=...&app_key=...&what=...&where=...&max_days_old=7&results_per_page=50`.
- Country coverage: confirm `in`, `gb`, `sg`, `au`, `us` and whether UAE is covered. **Verify at build.** If India coverage is thin, keep it for waves 2 and 3 only.
- Parse `company.display_name`, `title`, `created`, `redirect_url`, `location.display_name`. Classify with `classify_signal`. Create `hiring_frontdesk` or `hiring_builder` signals as with Apna.

---

## 5.14 Country-specific registries (backlog, verify before building)

These could be strong sources but were not tested yet. Each needs a robots and terms check and a CAPTCHA check before an adapter is written (Step 23 expansion playbook).

| Country | Registry | Gives | Status |
|---|---|---|---|
| India | State RERA portals (MahaRERA, HRERA, K-RERA, TS-RERA, UP-RERA) | Registered real estate agents and projects | Verify per state; many have CAPTCHA (skip those) |
| UAE | Dubai Land Department broker and office lists | Registered real estate brokers | Verify availability without login |
| UAE | DHA (Dubai) and DOH (Abu Dhabi) licensed facility lists | Licensed clinics | Verify public access |
| UAE | KHDA (Dubai) and ADEK (Abu Dhabi) lists | Schools, training and education centres | Verify public access |
| India | NABH accredited facilities list | Accredited hospitals and clinics (quality signal) | Verify format |

---

## 5.15 Sources deliberately not built (and why)

| Source | Why not |
|---|---|
| LinkedIn, X, Instagram pages | Founder rule (A.4.2), aggressive blocking and legal risk. LinkedIn and X appear only as search snippets (5.11) |
| Facebook groups, WhatsApp and Telegram groups | Need login or membership; collecting members' numbers breaks DPDP and spam rules |
| Meta Ad Library, Google Ads Transparency | robots.txt disallows bots; no API for Indian commercial ads. The founder or associate checks ads by hand and records `ads_running` in the app |
| Google Maps scraping (gosom and similar) | Breaks Maps terms; GitHub runner IPs get blocked; the Balanced tier uses the official API. Kept only as an idea for a Lean tier, off |
| Google review scrapers | Breaks Maps terms |
| JobSpy, Naukri, Indeed internal APIs | Private APIs and fake app identities (A.4.2). Naukri and Indeed posts can appear through grounded search snippets |
| Justdial, IndiaMART, Sulekha | Terms ban scraping, numbers are masked or sold |
| Internshala | Blocks AI crawlers; only 2 relevant clinic front-desk jobs in target cities on 12 Nov 2026. May be revisited for startups and education |
| ABDM Health Facility Registry | CAPTCHA on public search, no bulk list |
| Google News RSS | robots.txt blocks `/rss` |
| Reddit | robots.txt blocks all bots; API needs approval |
| Paid data brokers (Apollo, Lusha and similar) | Founder rule: no paid lists, phones must be self-published |

---

## 5.16 Tests for adapters

1. **Parsers with fixtures:** each adapter has saved inputs in `tests/fixtures/sources/<adapter>/` (HTML pages, JSON responses, a 20-row parquet for Overture). Tests assert exact parsed fields.
2. **robots tests:** a fixture robots.txt that disallows `/search` makes `robots_allows` false for `/search?q=x` and true for `/clinic/abc`.
3. **Block tests:** a 403 response and a page containing "captcha" both raise `SourceBlocked`; the adapter sets `blocked_until` with the right backoff (24 hours, then 72 hours, then 7 days).
4. **Never-fetch test:** a LinkedIn URL raises `NeverFetch` before any network call (assert respx saw no request).
5. **Kill switch test:** `sources_enabled.apna = false` makes `enabled()` false and no requests happen.
6. **Places quota test:** the 231st details call of the day raises `QuotaReached` (India cap 230).
7. **Places storage test:** the 30-day cleanup nulls rating and review count but keeps `place_id`.
8. **Grounded search test:** an item whose URL is not in the grounding citations is dropped; a LinkedIn citation yields `snippet_only = true` and 6 points.
9. **Live smoke (manual, small):**
```bash
$ APP_ENV=dev uv run nlead universe --segment clinics-in --limit 20 --dry-run
$ APP_ENV=dev uv run nlead signals --segment clinics-in --limit 10 --dry-run --max-spend-inr 5
```
Check the printed counts, sample rows and `source_health` updates.

## 5.17 Pitfalls
- **Overture schema changes between releases.** Pin the column list in one place and test it against the new release in the monthly job before using it.
- **Places costs creep abroad.** The free allowance outside India is much smaller. Keep the daily caps per country.
- **Grey sources can disappear.** Apna may block at any time. The system must keep working without it (signals simply come from other adapters).
- **Fuzzy matching mistakes.** Two clinics with similar names in one city are common. Matching rules (Step 6) need website or phone agreement, not name alone, before merging.
- **robots.txt is not the whole story.** For `public` sources, read the site's terms before enabling. Practo stays off until the founder approves.

## 5.18 Done when
- [ ] `http.py` passes its tests: never-fetch list, robots, classify, block detection, per-host spacing, 6 MB cap.
- [ ] Every adapter implements the base contract, declares a policy, and writes `source_health` on success and on errors.
- [ ] `overture.py` returns clinics for Pune from the current release, and the week 1 data check report (counts, website and phone fill rates) is written to `docs/`.
- [ ] `places.py` finds ids for free, fetches details within the daily caps, stores only what the terms allow, and the 30-day cleanup works.
- [ ] `art_registry.py` imports the IVF registry rows for the 5 metros.
- [ ] `apna.py` creates `hiring_frontdesk` signals for at least one segment in a dry run, at 1 request per 6 seconds, and stops on a block.
- [ ] `careers_watch.py` turns a changed careers page fixture into a `hiring_frontdesk` signal with a verified quote.
- [ ] `gdelt.py` and `grounded_search.py` create signals with verified quotes (or `snippet_only` for LinkedIn and X).
- [ ] `practo.py` exists and is off by default (`sources_enabled.practo = false`).
- [ ] `osm.py` and `adzuna.py` exist; Adzuna coverage for India and UAE is checked and noted.
- [ ] The sources-not-built table (5.15) is copied into `docs/data-policy.md`.
- [ ] All adapter tests pass in CI with no network.

---

---

# Step 6: Universe builder and entity resolution

## 6.1 Goal
For every enabled segment (A.12.8), build and keep fresh a table of **real, de-duplicated businesses** (`businesses`), fed by Overture, Google Places, registries and OpenStreetMap. One real company must end up as exactly one `businesses` row, no matter how many sources mention it.

## 6.2 What you need before starting
- Step 2 done: tables `businesses`, `source_records`, `contacts`, `signals`, `settings`, `runs` exist, and extensions `pg_trgm` and `unaccent` are enabled.
- Step 3 done: segment YAML files load and validate.
- Step 5 done: adapters `sources/overture.py`, `sources/places.py`, `sources/art_registry.py`, `sources/osm.py` return records.
- `src/nument_engine/db.py` provides `fetch_all(sql, params)`, `fetch_one(sql, params)`, `execute(sql, params)` and `executemany(sql, rows)` over a psycopg 3 connection pool (Step 1).
- `src/nument_engine/budget.py` provides `guard(task, est_inr)` and `record(...)` (Step 19).

## 6.3 Files you create in this step
| File | Purpose |
|---|---|
| `engine/src/nument_engine/normalize.py` | Pure functions: names, domains, phones, cities, distance |
| `engine/src/nument_engine/pipeline/resolve.py` | Entity resolution: match a source record to a business, merge, chains |
| `engine/src/nument_engine/pipeline/universe.py` | Orchestrates sources per segment, calls resolve, updates statuses |
| `engine/tests/test_normalize.py`, `engine/tests/test_resolve.py` | Unit tests |

> `normalize.py` is a new module not listed in A.8. Add it to the repo layout when you build.

## 6.4 The universe in one picture
```
 segment YAML (cities, bboxes, localities, categories, queries, registries)
        |
        +--> [monthly] Overture pull (bbox + taxonomy)  --+
        +--> [daily]   Places ID search per locality     --+--> source_records --> resolve() --> businesses
        +--> [daily]   Places Details (new or stale, capped)+       (raw, per source)          (one row per real company)
        +--> [monthly] Registries (ART registry, RERA later)--+
        +--> [monthly] OSM gap fill (optional)            --+
```

## 6.5 Normalisation (`normalize.py`)
Everything that compares businesses goes through these functions. They are pure (no database, no network), so they are easy to test.

### 6.5.1 Names
Rules, applied in order:
1. Unicode NFKC, then lower case.
2. Replace `&` with `and`.
3. Remove punctuation except spaces (keep letters and digits in any script, including Arabic and Devanagari).
4. Remove legal suffixes at the end, repeatedly: `private limited`, `pvt ltd`, `pvt`, `ltd`, `limited`, `llp`, `inc`, `llc`, `l l c`, `fze`, `fzco`, `fz llc`, `co`, `and co`, `opc`.
5. Collapse spaces.
6. The result is `norm_name` (stored). For matching only, also build `match_key`: `norm_name` minus generic words (`the`, `clinic`, `clinics`, `centre`, `center`, `hospital`, `multispeciality`, `multispecialty`, `academy`, `institute`, `realty`, `properties`, `real estate`), tokens sorted alphabetically.

```python
# engine/src/nument_engine/normalize.py
import math, re, unicodedata
import phonenumbers
import tldextract

LEGAL_SUFFIXES = [
    "private limited", "pvt ltd", "pvt", "ltd", "limited", "llp", "inc", "llc",
    "l l c", "fze", "fzco", "fz llc", "and co", "co", "opc",
]
GENERIC_WORDS = {
    "the", "clinic", "clinics", "centre", "center", "hospital", "multispeciality",
    "multispecialty", "academy", "institute", "realty", "properties", "real", "estate",
}
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

def norm_name(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw or "").lower().replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        for suf in LEGAL_SUFFIXES:
            if s.endswith(" " + suf):
                s, changed = s[: -len(suf) - 1].strip(), True
    return s

def match_key(raw: str) -> str:
    toks = [t for t in norm_name(raw).split() if t not in GENERIC_WORDS]
    return " ".join(sorted(toks))
```

### 6.5.2 Websites to `web_domain`
- Parse with `tldextract`. `web_domain` is the registrable domain (`example.co.in`).
- **Ignore list** (these are not the business's own site; set `website` and `web_domain` to null and keep the URL only in `source_records.payload`): `practo.com`, `lybrate.com`, `justdial.com`, `sulekha.com`, `indiamart.com`, `facebook.com`, `instagram.com`, `linkedin.com`, `x.com`, `twitter.com`, `youtube.com`, `linktr.ee`, `wa.me`, `whatsapp.com`, `google.com`, `goo.gl`, `g.page`, `bit.ly`, `magicbricks.com`, `99acres.com`, `housing.com`, `nobroker.in`, `bayut.com`, `propertyfinder.ae`, `dubizzle.com`, `shiksha.com`, `collegedunia.com`, `zomato.com`, `swiggy.com`, `booking.com`, `makemytrip.com`, `tripadvisor.com`.
- **Shared-host builders**: many tenants share one registrable domain. For these, `web_domain` is the **full host** (for example `drsharma.wixsite.com`): `wixsite.com`, `blogspot.com`, `wordpress.com`, `webflow.io`, `myshopify.com`, `business.site`, `carrd.co`, `notion.site`, `sites.google.com`, `godaddysites.com`, `zohosites.in`, `zohosites.com`.
- Always store `website` as the normalised homepage URL: `https://` + host + `/` (drop query strings, fragments and `utm_` parameters).

```python
IGNORED_HOSTS = {
    "practo.com", "lybrate.com", "justdial.com", "sulekha.com", "indiamart.com", "facebook.com",
    "instagram.com", "linkedin.com", "x.com", "twitter.com", "youtube.com", "linktr.ee", "wa.me",
    "whatsapp.com", "google.com", "goo.gl", "g.page", "bit.ly", "magicbricks.com", "99acres.com",
    "housing.com", "nobroker.in", "bayut.com", "propertyfinder.ae", "dubizzle.com", "shiksha.com",
    "collegedunia.com", "zomato.com", "swiggy.com", "booking.com", "makemytrip.com", "tripadvisor.com",
}
SHARED_HOSTS = {
    "wixsite.com", "blogspot.com", "wordpress.com", "webflow.io", "myshopify.com", "business.site",
    "carrd.co", "notion.site", "sites.google.com", "godaddysites.com", "zohosites.in", "zohosites.com",
}
_tld = tldextract.TLDExtract(suffix_list_urls=())  # offline, uses bundled list; refresh monthly

def web_domain(url: str | None) -> str | None:
    if not url:
        return None
    ext = _tld(url.strip())
    if not ext.domain or not ext.suffix:
        return None
    registrable = f"{ext.domain}.{ext.suffix}".lower()
    host = ".".join(p for p in [ext.subdomain, ext.domain, ext.suffix] if p).lower()
    host = host[4:] if host.startswith("www.") else host
    if registrable in IGNORED_HOSTS:
        return None
    if registrable in SHARED_HOSTS or host.endswith(".sites.google.com"):
        return host
    return registrable

def homepage(url: str | None) -> str | None:
    dom = web_domain(url)
    if not dom:
        return None
    ext = _tld(url)
    host = ".".join(p for p in [ext.subdomain, ext.domain, ext.suffix] if p).lower()
    return f"https://{host}/"
```

### 6.5.3 Phones to E.164 plus type
- Parse with `phonenumbers.parse(raw, region)`, where `region` is the segment's country code (`IN`, `AE`).
- Keep only `is_valid_number` results. Store `phone_e164` (`+919812345678`).
- Type mapping: `MOBILE` to `mobile`; `FIXED_LINE` to `landline`; `TOLL_FREE` and `SHARED_COST` to `tollfree`; `FIXED_LINE_OR_MOBILE` to `mobile` for India when the national number starts with 6, 7, 8 or 9, otherwise `unknown`; everything else `unknown`.
- A number that appears on 5 or more different businesses is a **shared number** (call centre, aggregator, franchise HQ). Never use it as a match key, and never use it as reach.

```python
def phone(raw: str, region: str) -> tuple[str, str] | None:
    try:
        num = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    t = phonenumbers.number_type(num)
    PNT = phonenumbers.PhoneNumberType
    if t == PNT.MOBILE:
        kind = "mobile"
    elif t == PNT.FIXED_LINE:
        kind = "landline"
    elif t in (PNT.TOLL_FREE, PNT.SHARED_COST):
        kind = "tollfree"
    elif t == PNT.FIXED_LINE_OR_MOBILE:
        nat = str(num.national_number)
        kind = "mobile" if region == "IN" and nat[:1] in "6789" else "unknown"
    else:
        kind = "unknown"
    return e164, kind
```

### 6.5.4 Cities and localities
- Each segment YAML lists `cities[]` with `name`, `bbox` (`[min_lng, min_lat, max_lng, max_lat]`), `aliases` and `localities[]`.
- City = the first city whose bbox contains the point (`lat`, `lng`). If there is no point, match the address text against `name` and `aliases` (for example `Gurgaon` to `Gurugram`, `Bangalore` to `Bengaluru`, `Bombay` to `Mumbai`).
- Locality = Places `addressComponents` of type `sublocality_level_1` or `neighborhood`, else Overture `addresses[0].locality`, else the closest locality name from the YAML found in the address text.

```python
def city_for(lat: float | None, lng: float | None, address: str, cities: list[dict]) -> str | None:
    if lat is not None and lng is not None:
        for c in cities:
            min_lng, min_lat, max_lng, max_lat = c["bbox"]
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                return c["name"]
    low = (address or "").lower()
    for c in cities:
        if any(a.lower() in low for a in [c["name"], *c.get("aliases", [])]):
            return c["name"]
    return None

def meters(lat1, lng1, lat2, lng2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
```

### 6.5.5 Unit tests to write first
| Input | Expected |
|---|---|
| `norm_name("Dr. Sharma's Skin & Hair Clinic Pvt. Ltd.")` | `"dr sharma s skin and hair clinic"` |
| `match_key("The Smile Dental Clinic")` | `"dental smile"` |
| `web_domain("https://www.practo.com/delhi/clinic/x")` | `None` |
| `web_domain("https://drx.wixsite.com/home")` | `"drx.wixsite.com"` |
| `web_domain("https://www.example.co.in/about?utm_source=x")` | `"example.co.in"` |
| `phone("098100 12345", "IN")` | `("+919810012345", "mobile")` |
| `phone("011 4567 8901", "IN")` | `("+911145678901", "landline")` |
| `phone("1800 123 4567", "IN")` | `("+9118001234567", "tollfree")` (verify the exact toll-free parse at build) |
| `phone("04 123 4567", "AE")` | `("+97141234567", "landline")` |
| `city_for(28.46, 77.03, "", cities)` | `"Gurugram"` |

## 6.6 Entity resolution (`pipeline/resolve.py`)

### 6.6.1 The input: a normalised candidate
Every adapter's raw record is turned into a `Candidate`:

```python
# engine/src/nument_engine/pipeline/resolve.py
from dataclasses import dataclass, field

@dataclass
class Candidate:
    source: str                 # "overture" | "places" | "art_registry" | "osm" | "apna" | "grounded_search" | ...
    source_key: str             # stable id inside that source (overture id, place_id, registry no, job id)
    segment_id: str
    name: str
    category: str | None = None
    subcategory: str | None = None
    website: str | None = None
    phones: list[tuple[str, str]] = field(default_factory=list)   # [(e164, type)]
    emails: list[str] = field(default_factory=list)
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    place_id: str | None = None
    overture_id: str | None = None
    rating: float | None = None
    review_count: int | None = None
    payload: dict = field(default_factory=dict)  # raw record, kept in source_records
```

### 6.6.2 Matching rules, in priority order
The first rule that finds a match wins.

| # | Rule | Why | Guard |
|---|---|---|---|
| 1 | Same (`source`, `source_key`) already in `source_records` | We have seen this exact record before | None |
| 2 | Same `place_id` or same `overture_id` on a business | Stable ids from the source | None |
| 3 | Same `web_domain` (not null, not in the ignore list) | One website means one company | If the existing business is more than 300 m away, it is the same company with another **branch** (6.6.5) |
| 4 | Same `phone_e164` on a business | Published phone is strong evidence | Skip shared numbers (used by 5 or more businesses) and toll-free numbers |
| 5 | Name similarity at least 92 (`rapidfuzz.fuzz.token_set_ratio` on `match_key`) **and** distance at most 300 m | Same name at the same spot | Only compare within the same city. If either side has no point, require similarity at least 96 and the same locality |
| 6 | None of the above | New business | Insert with status `candidate` |

### 6.6.3 Candidate lookup SQL
Rule 5 uses the trigram index on `norm_name` to keep the comparison small.

```sql
-- candidates for fuzzy name match inside one city (rule 5)
select id, name, norm_name, lat, lng, locality
from businesses
where segment_id = %(segment_id)s
  and city = %(city)s
  and norm_name %% %(norm_name)s           -- pg_trgm similarity operator (escaped for psycopg)
order by similarity(norm_name, %(norm_name)s) desc
limit 15;
```

```sql
-- shared phone numbers (exclude from matching and reach)
select phone_e164, count(distinct business_id) as n
from contacts
where phone_e164 is not null
group by phone_e164
having count(distinct business_id) >= 5;
```

### 6.6.4 Merge rules (which value wins)
When a candidate matches an existing business, update fields by **source precedence**. Never overwrite a better source with a worse one.

| Field | Precedence (best first) |
|---|---|
| `name` | Places `displayName` > own website title or JSON-LD name (Step 9) > Overture `names.primary` > registry > job board employer name |
| `website`, `web_domain` | Own website evidence > Places `websiteUri` > Overture `websites[0]` > registry |
| `lat`, `lng` | Places > Overture > OSM |
| `address`, `locality` | Places > Overture > registry |
| `category`, `subcategory` | Segment mapping of Overture taxonomy > Places `primaryType` > registry (for example ART registry means `subcategory = ivf`) |
| `rating`, `review_count` | Places only, and only if `places_fetched_at` is within 30 days (A.4.4) |
| Phones | Each phone becomes a `contacts` row (`source` = `website`, `google_listing`, `registry` or `other`); never delete phones, mark them |
| `last_seen_at` | Always `now()` when any source mentions the business |

Every candidate always writes or updates its `source_records` row (`source`, `source_key`, `business_id`, `payload`, `fetched_at`), even when nothing in `businesses` changes.

### 6.6.5 Chains and branches
- If two or more places share one `web_domain` and are more than 300 m apart, they are **one business with several branches**.
- Cluster the points of that domain with a simple greedy 300 m radius. `branches_count` = number of clusters.
- `city` = the city with the most branches. `lat` and `lng` = the branch in that city with the most reviews.
- Keep the branch list in the Places or Overture `source_records.payload` (one record per branch). Do not create one business per branch.
- Large chains (10 or more branches, or listed in `config/exclusions.yaml`) are still stored, but Step 8 rejects them.

### 6.6.6 Statuses this step sets
| Situation | Status |
|---|---|
| New business | `candidate` |
| Business seen again | unchanged, `last_seen_at = now()` |
| Places `businessStatus = CLOSED_PERMANENTLY`, or missing from 2 consecutive monthly Overture releases and not seen by any other source for 60 days | `dormant` |
| A dormant business seen again by a fresh source | back to `candidate` |

### 6.6.7 Merging two businesses that turn out to be the same
Sometimes a later fact (Step 9 finds the website) shows two rows are one company. `merge_businesses(keep_id, drop_id)` does this in one transaction:
1. Move `source_records`, `signals`, `pages`, `facts`, `contacts` and `scores` from `drop_id` to `keep_id` (skip rows that would break unique constraints, such as duplicate `pages.url`).
2. Leads: if only `drop_id` has a lead, move it. If both have leads, keep the one with more `activities` and close the other with stage `not_a_fit` and an activity note `merged into {keep_id}`.
3. Keep the better field values by the precedence table in 6.6.4.
4. Delete the `drop_id` business row.
5. Write an `activities` row (`source = 'engine'`, `type = 'merge'`) on the surviving lead, if any.

```python
def resolve(c: Candidate, seg: "Segment") -> tuple[str, str]:
    """Returns (business_id, action) where action is 'linked' | 'matched' | 'branch' | 'created'."""
    row = db.fetch_one(
        "select business_id from source_records where source=%s and source_key=%s",
        (c.source, c.source_key),
    )
    if row and row["business_id"]:
        _apply_merge(row["business_id"], c)
        _upsert_source_record(row["business_id"], c)
        return row["business_id"], "linked"

    bid = _by_ids(c) or _by_domain(c) or _by_phone(c) or _by_name_and_place(c, seg)
    if bid:
        action = "branch" if _is_far_branch(bid, c) else "matched"
        _apply_merge(bid, c)
        if action == "branch":
            _recount_branches(bid)
    else:
        bid = _insert_business(c, seg)
        action = "created"
    _upsert_source_record(bid, c)
    _upsert_contacts(bid, c)
    return bid, action
```

## 6.7 The universe run (`pipeline/universe.py`)

### 6.7.1 Command
```bash
$ uv run nlead universe --env dev --segment clinics-in --limit 500 --dry-run
$ uv run nlead universe --env prod --monthly          # all enabled segments, full refresh
```
- Without `--monthly` it runs the **daily** part only (Places ID search for a slice of localities, Places Details within caps).
- With `--monthly` it also runs Overture, registries and OSM.

### 6.7.2 Daily part (runs inside the night run)
1. Load enabled segments (`settings.segments_enabled` and `segments.enabled`).
2. Pick today's **locality slice** for each segment: `localities` rotate so every locality is searched about once every 14 days. Slice size = ceil(number of localities / 14).
3. For each locality and each query in `places.queries` (for example `"dermatology clinic in {locality}, {city}"`), call `places.search_ids()`. This is the free IDs-only Text Search (field mask `places.id,nextPageToken`). Follow `nextPageToken` up to 3 pages (60 results max per query).
4. For every returned `place_id`:
   - If it is already linked in `source_records`, update `last_seen_at` only.
   - If it is new, add it to the **details queue**.
5. Also add to the details queue any business that is `queued`, `researched` or `qualified` and whose `places_fetched_at` is older than 30 days (refresh rule, A.4.4).
6. Spend the **details budget**: up to `places.details_per_day` from the segment YAML (India default 230, abroad default 30), and never more than the Cloud console quota. Call `places.details(place_id, tier="enterprise")` with field mask `id,displayName,formattedAddress,addressComponents,location,rating,userRatingCount,websiteUri,nationalPhoneNumber,internationalPhoneNumber,businessStatus,primaryType,types` (verify field names at build).
7. Turn each detail response into a `Candidate` (`source="places"`, `source_key=place_id`) and call `resolve()`.
8. Store the listing phone as a `contacts` row with `source = 'google_listing'`. It is a fallback only (A.4.3).
9. Write counts to `runs.stats["universe"]`.

### 6.7.3 Monthly part (first day of the month, or `--monthly`)
1. **Overture**: for each city bbox and the segment's `overture.categories` list, call `overture.pull(bbox, categories, release)`. The adapter returns places with id, names, categories (`taxonomy`), websites, phones, addresses, confidence and operating status. Skip `confidence < 0.6` (verify the threshold against India data in week 1). Resolve each one.
2. **New places**: compare this release's Overture ids with last month's (kept in `source_records` where `source='overture'`). Ids that are new this release **and** created a new business become `new_place` signals in Step 7.
3. **Registries**: for each entry in the segment's `registries` list (wave 1: `art_registry` for `clinics-in`), pull and resolve. ART records set `subcategory = 'ivf'`. Registry emails become `contacts` rows with `source = 'registry'`.
4. **OSM gap fill** (optional, `osm.enabled` in the YAML): query Overpass by bbox for the segment's OSM tags (for example `healthcare=dentist`). Resolve with the lowest precedence.
5. **Dormant sweep**: apply the rules in 6.6.6.

### 6.7.4 Skeleton
```python
# engine/src/nument_engine/pipeline/universe.py
from nument_engine import db, budget, segments as seglib
from nument_engine.sources import overture, places, art_registry, osm
from nument_engine.pipeline.resolve import resolve, Candidate

def run_universe(env, segment_ids=None, monthly=False, limit=None, dry_run=False, run_id=None) -> dict:
    stats = {}
    for seg in seglib.enabled(segment_ids):
        s = stats.setdefault(seg.id, {"linked": 0, "matched": 0, "branch": 0, "created": 0, "details": 0})
        if monthly:
            for city in seg.cities:
                for c in overture.pull(city.bbox, seg.overture.categories, seg=seg, limit=limit):
                    _count(s, resolve(c, seg)[1], dry_run)
            for reg in seg.registries:
                for c in REGISTRY_ADAPTERS[reg].pull(seg=seg, limit=limit):
                    _count(s, resolve(c, seg)[1], dry_run)
            if seg.osm.enabled:
                for c in osm.pull(seg=seg, limit=limit):
                    _count(s, resolve(c, seg)[1], dry_run)
        new_ids = []
        for loc, city in _locality_slice(seg):
            for q in seg.places.queries:
                for pid in places.search_ids(q.format(locality=loc, city=city.name), seg=seg):
                    if not db.fetch_one("select 1 from source_records where source='places' and source_key=%s", (pid,)):
                        new_ids.append(pid)
        queue = new_ids + _stale_places(seg)
        cap = min(seg.places.details_per_day, places.remaining_quota(seg.country))
        for pid in queue[:cap]:
            if not budget.guard("places_details", est_inr=0.0):   # inside free caps; guard still checks quota
                break
            c = places.details_candidate(pid, seg=seg)
            s["details"] += 1
            if c:
                _count(s, resolve(c, seg)[1], dry_run)
    db.execute("update runs set stats = jsonb_set(coalesce(stats,'{}'), '{universe}', %s::jsonb) where id=%s",
               (json.dumps(stats), run_id))
    return stats
```

> In `--dry-run`, `resolve()` runs in a transaction that is rolled back at the end, and the counts are printed instead of written.

## 6.8 QA queries (run after the first universe build of each segment)
```sql
-- 1. how big is each universe, by city and source
select b.segment_id, b.city, sr.source, count(distinct b.id) as businesses
from businesses b join source_records sr on sr.business_id = b.id
group by 1, 2, 3 order by 1, 2, 3;

-- 2. duplicates by website (must be 0 rows)
select web_domain, count(*) from businesses
where web_domain is not null group by 1 having count(*) > 1;

-- 3. duplicates by place_id (must be 0 rows)
select place_id, count(*) from businesses
where place_id is not null group by 1 having count(*) > 1;

-- 4. likely fuzzy duplicates to eyeball (same city, very similar names)
select a.id, a.name, b.id, b.name, similarity(a.norm_name, b.norm_name) as sim
from businesses a join businesses b
  on a.segment_id = b.segment_id and a.city = b.city and a.id < b.id
 and a.norm_name % b.norm_name
where similarity(a.norm_name, b.norm_name) > 0.8
order by sim desc limit 50;

-- 5. contact coverage
select segment_id,
       count(*) as businesses,
       count(*) filter (where website is not null) as with_site,
       count(*) filter (where exists (select 1 from contacts c where c.business_id = businesses.id and c.phone_e164 is not null)) as with_phone
from businesses group by 1;

-- 6. random sample for a manual check (20 rows)
select id, name, city, locality, website, review_count from businesses
where segment_id = 'clinics-in' order by random() limit 20;
```
Manual check of the 20-row sample: open each website and Google listing. At least 18 of 20 must be real, operating businesses of the right type, with no obvious duplicates.

## 6.9 Pitfalls
- **The 60-result cap**: Places Text Search returns at most about 60 results per query. Search by locality, never by whole city.
- **Overture coverage in India is unknown** until week 1. If a category has few websites or phones, rely more on Places and registries for that segment.
- **Storing Places content too long** breaks Google's terms. Only `place_id` is permanent; refresh or null `rating` and `review_count` after 30 days (A.4.4).
- **Aggregator websites**: a Practo or Justdial URL in `websiteUri` is not the clinic's site. The ignore list handles it; extend it when you see new ones.
- **Shared numbers**: chains and call centres publish one number for many branches. The shared-number rule stops false merges.
- **Transliteration**: "Dr Sharma Skin Clinic" and "Dr. Sharmas Skin Care" can be one place. Rule 5 needs both name similarity and distance; when in doubt, keep two rows and let Step 9 merge them once a website is found.
- **UAE names**: free-zone suffixes (FZE, FZCO, FZ LLC) and Arabic names. Keep the Arabic name in `source_records.payload`; match on the English name when present.

## 6.10 Done when
- [ ] `normalize.py` unit tests pass (all rows of the 6.5.5 table).
- [ ] `resolve.py` unit tests cover rules 1 to 6, branch detection and `merge_businesses`.
- [ ] `nlead universe --monthly --segment clinics-in --env dev` completes for one city (start with Pune) and writes `runs.stats.universe`.
- [ ] QA queries 2 and 3 return 0 rows; query 4 shows no obvious duplicates in the top 20.
- [ ] The 20-row manual sample passes (18 of 20 or better).
- [ ] Places Details calls for the day never exceed `places.details_per_day`, and the Cloud console shows usage inside the free cap.
- [ ] Running the same command twice creates no new businesses the second time (idempotent).

---

---

# Step 7: Signal watchers

## 7.1 Goal
Every day, find **dated evidence that a business needs help now** and store it in `signals`, linked to a business. The signal types, categories, points and freshness windows are fixed in A.12.3. This step decides the pitch mode later (A.12.4), so evidence quality matters more than volume.

## 7.2 What you need before starting
- Step 6 done (`resolve()` exists, universe has data).
- Step 4 done (`llm.router.call(task, ...)` works for `classify_signal`, `classify_news`, `classify_page_change`, `grounded_search`).
- Step 5 adapters: `apna.py`, `careers_watch.py`, `gdelt.py`, `grounded_search.py`, `places.py`, `adzuna.py` (optional).

## 7.3 Files you create
| File | Purpose |
|---|---|
| `engine/src/nument_engine/pipeline/signals.py` | Runs all watchers, writes `signals`, links or creates businesses |
| `engine/tests/test_signals.py` | Dedupe keys, expiry, linking, review-pain storage rules |

## 7.4 Rules every watcher follows

### 7.4.1 The `Signal` object
```python
# engine/src/nument_engine/pipeline/signals.py
from dataclasses import dataclass, field
from datetime import datetime, timedelta

WINDOW_DAYS = {   # A.12.3 freshness windows
    "public_ask": 14, "tender": None, "hiring_builder": 30, "hiring_frontdesk": 30,
    "review_pain": 90, "ads_running": 30, "no_booking": 60, "slow_site": 60,
    "new_place": 60, "new_branch": 60, "news": 30, "funding": 120,
}
CATEGORY = {
    "public_ask": "stated_need", "tender": "stated_need", "hiring_builder": "stated_need",
    "hiring_frontdesk": "visible_pain", "review_pain": "visible_pain", "ads_running": "visible_pain",
    "no_booking": "visible_pain", "slow_site": "visible_pain",
    "new_place": "growth", "new_branch": "growth", "news": "growth", "funding": "money",
}
DEFAULT_POINTS = {
    "public_ask": 10, "tender": 10, "hiring_builder": 8, "hiring_frontdesk": 8, "review_pain": 6,
    "ads_running": 4, "no_booking": 3, "slow_site": 2, "new_place": 5, "new_branch": 5, "news": 3, "funding": 0,
}

@dataclass
class Signal:
    type: str
    source: str
    observed_at: datetime
    url: str | None
    quote: str | None
    evidence_key: str          # stable id of the evidence (job id, canonical URL, release, listing+month)
    business_id: str | None = None
    business_hint: dict = field(default_factory=dict)   # name, website, city, phone when not yet linked
    details: dict = field(default_factory=dict)
    deadline: datetime | None = None                    # tenders only
```

### 7.4.2 Points, expiry and category
- `category` comes from `CATEGORY[type]`.
- `points` = the segment's `signal_points[type]` if set in the YAML, else `DEFAULT_POINTS[type]`. The learning loop (Step 16) may later change segment overrides.
- `expires_at` = `observed_at + WINDOW_DAYS[type]`. For `tender`, `expires_at` = the submission deadline.
- `observed_at` is **when the event happened** (job posted date, review month, release date), not when we found it. If the source has no date, use our first-seen time and set `details.date_estimated = true`.
- Never store a signal whose `expires_at` is already in the past.

### 7.4.3 The dedupe key
```python
import hashlib, re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def canonical_url(u: str) -> str:
    p = urlsplit(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))]
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunsplit((p.scheme.lower() or "https", p.netloc.lower().removeprefix("www."), path, urlencode(q), ""))

def dedupe_key(sig: Signal, business_key: str) -> str:
    raw = f"{sig.type}|{business_key}|{sig.evidence_key}"
    return hashlib.sha1(raw.encode()).hexdigest()
```
- `business_key` = `business_id` when known, else `web_domain`, else `phone_e164`, else `match_key(name) + "|" + city`.
- `evidence_key` per type is defined in 7.5 (for example the job id, or `place_id + YYYY-MM` for review pain).

### 7.4.4 Evidence rules
- Every signal stores `url` and `quote`: the exact text (5 to 300 characters) that proves it, copied from the source.
- **Exception, `review_pain`**: Google's terms forbid storing review text (A.4.4). Store `quote = null`, `url` = the Google listing link (`https://www.google.com/maps/place/?q=place_id:{place_id}`), and only derived data in `details`, for example `{"flags": ["unanswered_calls", "booking_trouble"], "matching_reviews": 2, "of_reviews": 5}`.
- **Exception, search snippets**: for `public_ask` found through grounded search, `url` is the result URL (it may be a LinkedIn or X URL) and `quote` is the snippet text returned by the search tool. **We never fetch that URL** (A.4.2).

### 7.4.5 The upsert
```sql
insert into signals (business_id, type, category, points, observed_at, expires_at, source, url, quote, details, dedupe_key)
values (%(business_id)s, %(type)s, %(category)s, %(points)s, %(observed_at)s, %(expires_at)s,
        %(source)s, %(url)s, %(quote)s, %(details)s, %(dedupe_key)s)
on conflict (dedupe_key) do update
   set observed_at = greatest(signals.observed_at, excluded.observed_at),
       expires_at  = greatest(signals.expires_at,  excluded.expires_at),
       details     = signals.details || excluded.details,
       business_id = coalesce(signals.business_id, excluded.business_id);
```

### 7.4.6 Linking a signal to a business
1. If the watcher already knows the `business_id` (careers watch, review pain, research-derived signals), use it.
2. Otherwise build a `Candidate` from `business_hint` (`source` = the watcher name, `source_key` = the evidence key) and call `resolve()` from Step 6. It links to an existing business or **creates a new `candidate` business**. Businesses born from a signal are often the best leads, because the need came first.
3. If the hint has no city inside the segment's cities and no website, keep the signal unlinked (`business_id = null`) with `details.unlinked_reason`. A weekly QA query lists these.

## 7.5 The watchers, one by one

### 7.5.1 `hiring_frontdesk` and `hiring_builder` from Apna (India)
- **Source**: `sources/apna.py` (Step 5). Grey area: Apna's terms ban robots, so slow rate (1 request per 5 seconds), honest User-Agent, stop on any 403 or challenge page, kill switch `settings.sources_enabled.apna` (A.4.1).
- **Find new jobs**: read the job-listing sitemaps listed in `https://apna.co/api/sitemap-index.xml` (verify at build). Keep URLs whose path city slug is one of the segment's cities and whose title slug contains a keyword from the segment's `job_keywords.frontdesk` (receptionist, front desk, front office, telecaller, tele caller, patient coordinator, patient care, counsellor, admission counsellor, sales executive, site visit executive, customer support, relationship manager) or `job_keywords.builder` (developer, web developer, app developer, software, automation, ai, n8n, zapier, crm executive). Skip URLs seen before (`source_records` where `source = 'apna'`).
- **Fetch** each new job page, at most `apna.pages_per_day` (default 300). Parse the employer name, job title, posted date, address, salary and any `JobPosting` JSON-LD.
- **Classify** with `classify_signal` (Flash-Lite, cheap). Input: title, employer name, the first 1,500 characters of the description, address. Output schema:

```python
class SignalClassification(BaseModel):
    is_relevant: bool                    # a real business hiring for a role we care about
    role_category: Literal["frontdesk", "builder", "other"]
    employer_name: str | None
    employer_website: str | None
    employer_domain: Literal["clinics", "realestate", "education", "d2c", "hospitality", "auto",
                             "insurance_loans", "fitness_salon", "firms_startups", "agency_or_staffing", "other"]
    city: str | None
    evidence_quote: str                  # exact sentence from the input proving the role
    confidence: float                    # 0 to 1
```
- **Rules after classification**:
  - `employer_domain = agency_or_staffing` means a placement agency posting for someone else. Drop it.
  - `role_category = frontdesk` creates `hiring_frontdesk`. `builder` creates `hiring_builder`. `other` is dropped.
  - Drop if `confidence < 0.6`.
  - The employer's domain must map to the segment being processed. If it maps to another enabled segment, file it under that segment.
- `evidence_key` = Apna job id (the number at the end of the URL). `observed_at` = posted date. `url` = job URL. `quote` = `evidence_quote`.

### 7.5.2 `hiring_frontdesk`, `hiring_builder`, `new_branch` from company careers and locations pages
- **Source**: `sources/careers_watch.py`. It watches businesses in status `researched`, `qualified`, or with an open lead. Step 9 records each business's careers and locations page URLs as facts.
- **Daily**: re-fetch each watched URL (robots respected, 1 request per host), compare `text_hash` with the stored `pages.text_hash`. Unchanged pages cost nothing more.
- **Changed page**: send the old and new text (diff only, max 2,000 characters) to `classify_page_change`. The output says whether a new role appeared (with title and category) or a new branch or location appeared (with city and address), plus an exact quote from the new text.
- A new role creates `hiring_frontdesk` or `hiring_builder`. A new location creates `new_branch`.
- `evidence_key` = `canonical_url + "|" + sha1(quote)[:12]`.
- Budget: at most `careers_watch.pages_per_day` (default 500), one request per host per day.

### 7.5.3 `public_ask` from grounded search and the founder's inbox
- **Grounded search**: `sources/grounded_search.py` calls the `grounded_search` task (Gemini with Google Search) with the segment's `public_ask_queries`. Example for `clinics-in`: `"looking for" developer OR agency WhatsApp chatbot clinic India`. Ask the model to return only results from the last 14 days, each with title, URL, snippet, date and author or business name.
- **Classify** each result with `classify_signal`. Keep only real businesses asking for a builder or a vendor. Drop job seekers, agencies advertising themselves, and students.
- **Never fetch** the result URL when it is on linkedin.com, x.com, twitter.com or instagram.com. Use the snippet only.
- `evidence_key` = `canonical_url`. `observed_at` = the date in the result (if none, today with `details.date_estimated = true`).
- **Founder inbox**: rows in `inbox_posts` (pasted from LinkedIn or X in the web app, Step 15) with `status = 'new'` go through the same classification. The founder's pasted text is the quote and the pasted URL is the url. Set the row's `status` to `processed` or `rejected`.
- **Budget**: grounded searches count against the 5K free per month. Daily cap `grounded_search.per_day` (default 160, shared with Step 9 decision-maker lookups). The budget guard tracks it.

### 7.5.4 `tender`
- Wave 1: not built. The type exists in the contract so wave 2 can add NGO RFP sites (DevNetJobs, NGOBox) and government portals (GeM) without schema changes.
- When built: `evidence_key` = tender reference number; `expires_at` = submission deadline; `quote` = the scope sentence.

### 7.5.5 `review_pain` from Google reviews
- **Who gets checked**: businesses that are `queued` or `researched` today, plus open leads whose last review check is older than 30 days. Never the whole universe (cost and terms).
- **Call**: `places.details(place_id, tier="enterprise_atmosphere")` with field mask `id,reviews` (verify at build). Budget: `places.reviews_per_day` (India 230, abroad 30).
- **Classify in memory** with `classify_signal` in review mode. Input: the up to 5 review texts and their relative dates. Output: `flags` (any of `unanswered_calls`, `slow_whatsapp`, `booking_trouble`, `long_wait`, `rude_front_desk`), `matching_reviews` (how many reviews mention a flag) and `newest_flag_age_days`.
- Create `review_pain` only if `matching_reviews >= 1` and the newest matching review is at most 90 days old.
- **Store no review text** (A.4.4). `quote = null`. `url` = listing link. `details` = flags and counts. The message writer (Step 12) may say "a few reviews mention calls going unanswered", never quote a review.
- `evidence_key` = `place_id + "|" + YYYY-MM` (one review signal per business per month).

### 7.5.6 `ads_running` (manual)
- Ad libraries block automated access (Meta's robots.txt disallows everything), so this signal is **entered by a person** in the web app (Step 15): on a lead page, "Running ads?" with a URL field (the ad library page they looked at) and a short note.
- The app inserts the signal directly: `source = 'manual'`, `quote` = the note, `url` = what they pasted, `observed_at` = now, `expires_at` = now + 30 days, `dedupe_key` = `sha1('ads_running|' || business_id || '|' || to_char(now(), 'YYYY-MM'))`.
- The app shows "check ads" only on the top 150 leads of the day (as agreed), so this stays a few minutes of work.

### 7.5.7 `no_booking` and `slow_site` (from research)
- Created in Step 9 from the tech detection and PageSpeed results, not by a watcher. Listed here so every type has an owner.
- `no_booking`: no booking widget, no WhatsApp link, no chat widget, and no booking words on any fetched page. `evidence_key` = `web_domain + "|" + YYYY-MM`. `quote` = a short factual line generated by code ("No booking form, WhatsApp link or chat widget found on 6 pages checked"), `url` = homepage.
- `slow_site`: mobile performance under 40. `evidence_key` = `web_domain + "|" + YYYY-MM`. `quote` = "PageSpeed mobile score 31", `url` = homepage.

### 7.5.8 `new_place` (from the monthly Overture release)
- Overture ids that appear for the first time this release **and** created a new business in Step 6 (action `created`).
- `observed_at` = the release date (from the release name, for example `2026-10-21.0`). `evidence_key` = `overture_id`. `url` = the business website if known, else null. `quote` = `"New in Overture release {release}: {name}, {locality}"`.
- Also: a Places search that finds a **new place_id whose website matches an existing business** is a new branch. Create `new_branch` with `evidence_key = place_id`.

### 7.5.9 `news`, `new_branch` and `funding` from GDELT
- **Source**: `sources/gdelt.py`, the free DOC API (`https://api.gdeltproject.org/api/v2/doc/doc`, `mode=ArtList`, `format=json`, `timespan=1d`, `maxrecords=100`, verify at build). Queries come from the segment's `news_queries`, for example `("new clinic" OR "opens" OR "launches") (dermatology OR IVF OR dental) sourcecountry:IN`. At most `gdelt.queries_per_day` (default 30).
- **Classify** each article title and first paragraph with `classify_news`. Output: business name, website if mentioned, city, `event` (`new_branch`, `launch`, `expansion`, `funding`, `award`, `irrelevant`), the amount for funding, and an exact quote.
- Mapping: `new_branch` and `expansion` create `new_branch`; `launch` and `award` create `news`; `funding` creates `funding` (money category, 0 intent points, adds can-pay in Step 11).
- `evidence_key` = canonical article URL.
- GDELT's terms ask for attribution. Store `details.source = "GDELT"`. Only the article's own URL is shown to the founder.

### 7.5.10 Adzuna (optional, verify at build)
If week 2 confirms Adzuna's official API covers India and the UAE, add `sources/adzuna.py` as a second job source with the same classification and rules as 7.5.1 (`evidence_key` = Adzuna job id). It is official, so it is preferred over Apna wherever it has coverage.

## 7.6 Daily budgets for all watchers
| Watcher | Unit | Default daily cap | Setting key |
|---|---|---|---|
| Apna job pages | page fetch | 300 | `segments.*.apna.pages_per_day` |
| Careers and locations pages | page fetch | 500 (1 per host) | `careers_watch.pages_per_day` |
| Grounded search | query | 160 (shared with Step 9) | `grounded_search.per_day` |
| GDELT | query | 30 | `gdelt.queries_per_day` |
| Places reviews | Details call | India 230, abroad 30 | `segments.*.places.reviews_per_day` |
| `classify_signal` / `classify_news` / `classify_page_change` | AI call (Flash-Lite) | 1,500 total | `ai.classify_per_day` |

All caps are also checked against the money cap through `budget.guard()` before each call.

## 7.7 The signals run
```python
def run_signals(env, segment_ids=None, limit=None, dry_run=False, run_id=None) -> dict:
    stats = {}
    for seg in seglib.enabled(segment_ids):
        watchers = [apna_watch, careers_watch_run, grounded_public_asks, inbox_posts_watch,
                    review_pain_watch, gdelt_watch] + ([adzuna_watch] if seg.adzuna_enabled else [])
        for w in watchers:
            if not source_enabled(w.source):          # kill switch per source (settings.sources_enabled)
                continue
            try:
                for sig in w(seg, limit=limit):
                    bid = sig.business_id or link_or_create(sig, seg)
                    if bid is None and not sig.business_hint:
                        continue
                    row = to_row(sig, bid, seg)
                    if not dry_run:
                        db.execute(UPSERT_SIGNAL_SQL, row)
                    stats.setdefault(seg.id, {}).setdefault(sig.type, 0)
                    stats[seg.id][sig.type] += 1
                mark_source_ok(w.source)
            except SourceBlocked as e:
                mark_source_blocked(w.source, str(e))    # sets source_health.blocked_until = now() + 7 days
            except Exception as e:
                mark_source_error(w.source, str(e))
    save_stats(run_id, "signals", stats)
    return stats
```
- A blocked source (403, challenge page, CAPTCHA marker) is **never retried with tricks**. It is paused for 7 days and shown on the web app's Engine page (Step 15).

## 7.8 QA queries
```sql
-- signals found per day and type (last 14 days)
select date_trunc('day', created_at) as day, type, count(*)
from signals where created_at > now() - interval '14 days'
group by 1, 2 order by 1 desc, 2;

-- link rate: signals without a business (target under 10%)
select type, count(*) filter (where business_id is null) * 100.0 / count(*) as pct_unlinked
from signals where created_at > now() - interval '7 days' group by 1;

-- review_pain must never store text (must be 0)
select count(*) from signals where type = 'review_pain' and quote is not null;

-- businesses created by signals (often the best leads)
select sr.source, count(*) from source_records sr
join businesses b on b.id = sr.business_id
where sr.source in ('apna', 'grounded_search', 'gdelt', 'careers_watch')
  and b.created_at > now() - interval '7 days'
group by 1;
```

## 7.9 Pitfalls
- **Staffing agencies** post jobs for clients. The classifier's `agency_or_staffing` label plus `config/exclusions.yaml` keywords catch most. Spot-check 10 Apna signals a week.
- **Evergreen or ghost jobs**: the same role reposted every month. The dedupe key is the job id, and a repost with a new id is a new signal, which is acceptable. A business with 5 or more front-desk posts in 60 days likely has high turnover: keep the newest signal only (`details.repost_count`).
- **Old posts through search**: grounded search sometimes returns old posts. Always parse the date and drop anything older than 14 days.
- **Review language**: reviews in Hindi, Arabic or mixed language. The classifier handles them; do not translate or store them.
- **Over-signalling**: one event (a funding round) can show up as news, a careers change and a job post. Step 11 counts independent signal **types**, not rows, for the stacking bonus.

## 7.10 Done when
- [ ] Each implemented watcher has a unit test with a saved fixture (Apna page, careers diff, GDELT JSON, grounded search result, review set) and produces the right `Signal`.
- [ ] `nlead signals --env dev --segment clinics-in --limit 50` writes signals with correct `category`, `points`, `expires_at` and `dedupe_key`.
- [ ] Running it twice creates no duplicate rows.
- [ ] `review_pain` rows have `quote is null` (QA query returns 0).
- [ ] No request was made to linkedin.com, x.com, twitter.com or instagram.com (check the HTTP log).
- [ ] A blocked source shows `blocked_until` in `source_health`, and the run still finishes.
- [ ] Manual `ads_running` entry from the app (Step 15) appears in `signals` with `source = 'manual'`.
- [ ] Spot check: 10 random signals, each with evidence that a person agrees proves the need.

---

---

# Step 8: Rule pre-filter and research queue

## 8.1 Goal
Using **only free rules** (no AI, no paid API), pick the best businesses to research tonight: at most `settings.research_per_day` (300), ordered by how likely they are to be good leads now. Everything that cannot become a good lead is rejected here, before we spend money.

## 8.2 What you need before starting
- Steps 6 and 7 done.
- `engine/config/exclusions.yaml` created (8.4).
- `suppression` table in use (Step 18).

## 8.3 Files you create
| File | Purpose |
|---|---|
| `engine/src/nument_engine/pipeline/prefilter.py` | Rules, priority, queue |
| `engine/config/exclusions.yaml` | Chains, hospitals, giants, agencies to skip |
| `engine/tests/test_prefilter.py` | One test per rule, priority ordering, quotas |

> This step adds two columns to `businesses` that are not in A.12.1: `queued_at` (timestamptz) and `queue_priority` (real). Add them in the Step 2 migration when you build.

## 8.4 `exclusions.yaml`
Lists are a starting point. Verify and extend them at build, and add to them whenever the founder marks a lead "Not a fit" because it is a big chain.

```yaml
# engine/config/exclusions.yaml
chains:                      # matched on norm_name (regex) or web_domain
  - { name: "apollo",          domains: ["apollohospitals.com", "apollo247.com", "apolloclinic.com"] }
  - { name: "fortis",          domains: ["fortishealthcare.com"] }
  - { name: "max healthcare",  domains: ["maxhealthcare.in"] }
  - { name: "manipal",         domains: ["manipalhospitals.com"] }
  - { name: "narayana",        domains: ["narayanahealth.org"] }
  - { name: "aster",           domains: ["asterdmhealthcare.com", "asterhospitals.in", "asterclinic.ae"] }
  - { name: "cloudnine",       domains: ["cloudninecare.com"] }
  - { name: "indira ivf",      domains: ["indiraivf.com"] }
  - { name: "nova ivf",        domains: ["novaivffertility.com"] }
  - { name: "birla fertility", domains: ["birlafertility.com"] }
  - { name: "clove dental",    domains: ["clovedental.in"] }
  - { name: "kaya",            domains: ["kaya.in"] }
  - { name: "vlcc",            domains: ["vlccwellness.com"] }
  - { name: "dlf",             domains: ["dlf.in"] }
  - { name: "godrej properties", domains: ["godrejproperties.com"] }
  - { name: "lodha",           domains: ["lodhagroup.in", "lodhagroup.com"] }
  - { name: "prestige",        domains: ["prestigeconstructions.com"] }
  - { name: "sobha",           domains: ["sobha.com"] }
  - { name: "emaar",           domains: ["emaar.com"] }
  - { name: "damac",           domains: ["damacproperties.com"] }
  - { name: "nakheel",         domains: ["nakheel.com"] }
  - { name: "byju",            domains: ["byjus.com"] }
  - { name: "physicswallah",   domains: ["pw.live"] }
  - { name: "allen",           domains: ["allen.ac.in"] }
  - { name: "aakash",          domains: ["aakash.ac.in"] }
  - { name: "unacademy",       domains: ["unacademy.com"] }
  - { name: "upgrad",          domains: ["upgrad.com"] }
hospital_keywords: ["hospital", "medical college", "institute of medical sciences", "super speciality hospital"]
agency_keywords:             # in name, category or site title: competitors, never prospects
  - "digital marketing agency"
  - "software development company"
  - "web development company"
  - "it services"
  - "app development company"
  - "seo agency"
  - "marketing agency"
  - "placement consultancy"
  - "staffing"
max_branches: 10             # 10 or more branches = big chain, skip
```

## 8.5 The rules, in order
The first rule that fails rejects the business. Set `status = 'rejected'` and `reject_reason` to the rule code, except where the table says "skip for now" (no status change).

| Code | Rule | On fail |
|---|---|---|
| `R1_segment` | Segment enabled, and `city` is one of the segment's cities | Skip for now |
| `R2_category` | `category` or `subcategory` is in the segment's allowed list | Reject |
| `R3_excluded` | Not in `exclusions.yaml` (chains by name or domain, hospital keywords, `branches_count >= max_branches`) | Reject |
| `R4_agency` | Name or category does not contain an agency keyword | Reject |
| `R5_suppressed` | No `suppression` row matches its phones, emails or `web_domain` | Status `suppressed` |
| `R6_open_lead` | No lead for this business with a stage that is not closed (A.12.2) | Skip for now |
| `R7_cooldown` | No lead closed in the last 90 days, **unless** a new `stated_need` signal arrived after it closed | Skip for now |
| `R8_recent` | Not researched in the last 90 days, **unless** a new active signal arrived after `researched_at` | Skip for now |
| `R9_size` | Passes the segment's `size_rules` (8.6), or has an active `stated_need` signal | Skip for now (waits for Places data) |
| `R10_reach` | Has a website, or at least one phone or email in `contacts` | Reject (`no_contact_route`) |
| `R11_dormant` | Status is not `dormant` | Skip |

## 8.6 Size rules per segment
Size rules come from each segment YAML (`size_rules`). Defaults for wave 1:

| Segment | Passes size if any of these is true |
|---|---|
| `clinics-in`, `clinics-ae` | `review_count >= 100`, or `branches_count >= 2`, or on the ART registry, or a Practo fact `staff_or_doctors >= 2` from an earlier research |
| `realestate-in`, `realestate-ae` | `review_count >= 30`, or `branches_count >= 2`, or on a RERA or DLD registry (when added) |
| `education-in`, `education-ae` | `review_count >= 50`, or `branches_count >= 2` |
| Any segment | An active `stated_need` signal (they asked; size is checked later in Step 11) |

- **Unknown size** (no Places details yet, not on a registry) is skipped, not rejected. Step 6 fetches the details and the business returns tomorrow.
- These thresholds are tuned with the golden set (Step 17).

## 8.7 Priority score for the queue
For every business that passes, compute:

```
best_signal   = the active signal with the highest points x freshness
strength      = best_signal.points / 10                          (0 to 1)
freshness     = 1.0 if age <= 30% of window, 0.7 if <= 60%, 0.4 if <= 100%
size_bonus    = min(20, 6 x log10(review_count + 1) + 4 x (branches_count - 1))
type_bonus    = 15 if best_signal.category = 'stated_need'
                 8 if best_signal.category = 'visible_pain'
                 0 otherwise
segment_w     = settings.segment_weights[segment_id] (default 0; Step 16 may change it)

priority      = 100 x strength x freshness + type_bonus + size_bonus + segment_w
fit_only      = no active signal at all  ->  priority = size_bonus + segment_w
```
Tie breakers: newer `best_signal.observed_at` first, then more reviews.

## 8.8 Building today's queue
1. `slots` = `settings.research_per_day` (300) minus businesses already researched today.
2. **Money check**: `est_cost_per_item` = expected AI cost of one researched business (extraction batch, plus the share that reaches judging and messaging). The Balanced-tier default is about ₹2.1 (verify against real `costs` after week 1). `slots = min(slots, floor(budget.remaining_inr_today() x 0.8 / est_cost_per_item))`. The 0.8 keeps room for the morning run.
3. **Fit-only quota**: at most 10% of `slots` go to fit-only businesses.
4. **Fairness**: every enabled segment with eligible businesses gets at least 10% of `slots`, so one busy segment cannot starve the others. The rest is filled by priority across all segments.
5. Write: `status = 'queued'`, `queued_at = now()`, `queue_priority = priority`.
6. Save the queue summary in `runs.stats.prefilter`: counts by segment, by signal category, fit-only share, and reject reasons.

## 8.9 Skeleton and SQL
```sql
-- candidates with their active signals, in one query
select b.*,
       coalesce(json_agg(json_build_object(
           'type', s.type, 'category', s.category, 'points', s.points,
           'observed_at', s.observed_at, 'expires_at', s.expires_at))
         filter (where s.id is not null), '[]') as active_signals
from businesses b
left join signals s
  on s.business_id = b.id and s.expires_at > now()
where b.status in ('candidate', 'researched', 'qualified')
  and b.segment_id = any(%(segments)s)
group by b.id;
```

```python
# engine/src/nument_engine/pipeline/prefilter.py
def run_prefilter(env, segment_ids=None, limit=None, dry_run=False, run_id=None) -> dict:
    segs = {s.id: s for s in seglib.enabled(segment_ids)}
    excl = load_exclusions()
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segs)})
    passed, rejects = [], Counter()
    for b in rows:
        verdict = apply_rules(b, segs[b["segment_id"]], excl)   # returns ("pass", None) | ("reject", code) | ("skip", code)
        if verdict[0] == "pass":
            passed.append((priority(b, segs[b["segment_id"]]), b))
        else:
            rejects[verdict[1]] += 1
            if verdict[0] == "reject" and not dry_run:
                db.execute("update businesses set status='rejected', reject_reason=%s where id=%s", (verdict[1], b["id"]))
    queue = build_queue(passed, slots=today_slots(), fit_only_share=0.10, min_segment_share=0.10)
    if limit:
        queue = queue[:limit]
    if not dry_run:
        db.executemany(
            "update businesses set status='queued', queued_at=now(), queue_priority=%s where id=%s",
            [(p, b["id"]) for p, b in queue],
        )
    stats = summarise(queue, rejects)
    save_stats(run_id, "prefilter", stats)
    return stats
```

## 8.10 QA queries
```sql
-- reject reasons (last run)
select reject_reason, count(*) from businesses
where updated_at > now() - interval '1 day' and status = 'rejected'
group by 1 order by 2 desc;

-- today's queue composition
select segment_id, count(*) as queued, round(avg(queue_priority)::numeric, 1) as avg_priority
from businesses where status = 'queued' and queued_at > now() - interval '1 day'
group by 1;

-- the cap must never be exceeded (must be <= 300)
select count(*) from businesses where queued_at::date = (now() at time zone 'Asia/Kolkata')::date;
```

## 8.11 Pitfalls
- **Chains slipping through** under a local franchise name. Match on `web_domain` too, not only names. Add every miss to `exclusions.yaml`.
- **Starving a segment** that has few signals. The 10% minimum share prevents this.
- **Stale Places numbers**: `review_count` older than 30 days is treated as unknown (A.4.4), so size can drop to unknown and the business waits a day for a refresh.
- **IVF registry entries without a website**: rule R10 still passes when the registry gives an email or a phone.
- **Over-rejecting**: rejections are permanent until a new signal arrives. When in doubt, prefer "skip for now".

## 8.12 Done when
- [ ] Unit tests cover every rule code, the priority formula, the fit-only cap, the per-segment minimum share and the money check.
- [ ] `nlead prefilter --env dev` produces a queue of at most 300 with the right composition.
- [ ] Reject reasons look sensible on a manual look at 20 rejected businesses (no good business wrongly rejected).
- [ ] No queued business is in `exclusions.yaml`, `suppression`, or has an open lead.
- [ ] Re-running on the same day does not grow the queue beyond the cap.

---

---

# Step 9: Deep research

## 9.1 Goal
For every `queued` business, read its own website (and Practo for Indian clinics), detect its tools, score its site, and extract **facts with exact quotes**. AI extraction runs as a cheap overnight batch: submitted in the night run, collected in the morning run. Nothing in this step decides whether a lead is good; it only gathers evidence for Steps 10 and 11.

## 9.2 What you need before starting
- Step 8 queue exists (`status = 'queued'`).
- `http.py` (polite fetch, robots cache, rate limits) from Step 5.
- Step 4 batch support: `llm.batch.submit(task, items)` and `llm.batch.collect(batch_id)`.
- Playwright Chromium installed (`uv run playwright install chromium`; cached in CI, Step 14).
- `GOOGLE_MAPS_API_KEY` with the PageSpeed Insights API enabled (Step 0).

## 9.3 Files you create
| File | Purpose |
|---|---|
| `engine/src/nument_engine/pipeline/research.py` | Crawl queued businesses, store pages, run tech and quality checks, create research signals |
| `engine/src/nument_engine/research/pages.py` | Choose which pages to read |
| `engine/src/nument_engine/research/text.py` | Main text and links (trafilatura, selectolax fallback) |
| `engine/src/nument_engine/research/structured.py` | JSON-LD and microdata (extruct) |
| `engine/src/nument_engine/research/techstack.py` | Widgets, CMS, ads tags |
| `engine/src/nument_engine/research/quality.py` | PageSpeed mobile score |
| `engine/src/nument_engine/pipeline/extract.py` | Build AI inputs, submit batch, collect results, write facts |
| `engine/tests/test_pages.py`, `test_techstack.py`, `test_extract.py` | Unit tests with saved HTML fixtures |

## 9.4 Page discovery (`research/pages.py`)

### 9.4.1 Start URL
1. Use `businesses.website`. If null, there is nothing to crawl: research uses only Places, registry and signal data (`details.no_website = true`), and the `no_booking` signal is not created (no evidence either way).
2. Fetch the homepage over `https://`. On a TLS error, try `http://` once. Follow up to 5 redirects.
3. If the final URL lands on an ignored host (6.5.2), for example a Facebook page, treat the business as having no website.

### 9.4.2 Robots
- Check `robots.txt` for the host through `http.robots_allows(url)` (cached for 24 hours per host), using our honest User-Agent (`USER_AGENT`).
- If the homepage is disallowed: store a `pages` row with `robots_allowed = false`, crawl nothing more on that host, and continue with non-website data. Never work around a disallow.
- Each further page is checked against the same robots rules.

### 9.4.3 Choosing pages
Parse homepage links (same registrable domain only, from `<a href>` and `<link rel="alternate">`). Score each link against keyword groups (URL path and anchor text, lower case):

| Group | Keywords (URL or anchor) | Priority |
|---|---|---|
| `team` | team, doctors, our-doctors, specialists, faculty, experts, people, leadership, founder, management | 1 |
| `contact` | contact, reach-us, locate, find-us, get-in-touch | 2 |
| `careers` | careers, jobs, join-us, hiring, work-with-us, vacancies, opportunities | 3 |
| `locations` | locations, branches, centres, centers, clinics, our-clinics, offices, campuses | 4 |
| `pricing` | pricing, price, packages, fees, plans, treatments, services, courses, programs, projects, properties, rooms | 5 |
| `booking` | book, appointment, schedule, enquiry, enquire, consultation, visit | 6 |
| `about` | about, story, who-we-are, our-story, overview | 7 |

Rules:
- Take the best link per group, up to **7 pages plus the homepage** (8 total).
- For UAE sites, also match Arabic anchors: `اتصل` (contact), `من نحن` (about), `فروعنا` (branches), `وظائف` (careers).
- Skip: other domains, `mailto:` and `tel:` (but **record** them as phone and email candidates), PDFs, images, `#` anchors, URLs with pagination or tag/category patterns, login and cart pages.
- **Sitemap fallback**: if fewer than 3 groups were found, read `/sitemap.xml` (and nested sitemap indexes, at most 2 levels, 500 URLs) and score the URLs the same way.
- Record `careers` and `locations` URLs as facts (`field = 'careers_url'` and `'locations_url'`, verified by code) so the careers watcher (7.5.2) can watch them.

```python
GROUPS = {
    "team": ["team", "doctors", "our-doctors", "specialists", "faculty", "experts", "people", "leadership", "founder", "management"],
    "contact": ["contact", "reach-us", "locate", "find-us", "get-in-touch"],
    "careers": ["careers", "jobs", "join-us", "hiring", "work-with-us", "vacancies", "opportunities"],
    "locations": ["locations", "branches", "centres", "centers", "clinics", "our-clinics", "offices", "campuses"],
    "pricing": ["pricing", "price", "packages", "fees", "plans", "treatments", "services", "courses", "programs", "projects", "properties", "rooms"],
    "booking": ["book", "appointment", "schedule", "enquiry", "enquire", "consultation", "visit"],
    "about": ["about", "story", "who-we-are", "our-story", "overview"],
}
SKIP = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|mp4|zip)$|/(tag|category|page)/\d*|login|signin|cart|checkout", re.I)

def choose_pages(home_url: str, links: list[tuple[str, str]], max_pages: int = 8) -> dict[str, str]:
    """links = [(absolute_url, anchor_text)] on the same registrable domain."""
    best: dict[str, tuple[int, str]] = {}
    for url, anchor in links:
        if SKIP.search(url):
            continue
        hay = (urlsplit(url).path + " " + anchor).lower()
        for group, words in GROUPS.items():
            hits = sum(1 for w in words if w in hay)
            if hits and (group not in best or hits > best[group][0]):
                best[group] = (hits, url)
    chosen = {"home": home_url}
    for group in sorted(best, key=lambda g: list(GROUPS).index(g)):
        if len(chosen) >= max_pages:
            break
        chosen[group] = best[group][1]
    return chosen
```

## 9.5 Fetching
- **Default: httpx** through `http.polite_get()`: 15 second timeout, at most 1 request per second per host, `Accept-Language: en`, 3 MB body cap, one retry on timeouts or 5xx errors.
- **Playwright fallback**: only when the httpx page yields under 400 characters of main text **and** looks like a JavaScript app (an empty `<div id="root">`, `<div id="__next">`, `id="app"`, or "enable JavaScript" text), or has fewer than 3 links. Settings: Chromium headless, block images, fonts and media, 20 second timeout, wait for network idle or 3 seconds. At most `research.browser_pages_per_run` renders (default 40) to protect the Actions time budget (Step 14.6). Store `render_mode = 'browser'`.
- **Blocks**: if the response is 403 or 429, or the HTML contains a challenge marker (`cf-chl`, `captcha`, `challenge-platform`, "verify you are human"), stop crawling that host, record `pages.http_status`, and move on. No retries with other headers, no browser to get around it (A.4.2).
- Concurrency: up to 8 hosts at once with asyncio. Pages of one host are fetched one after another.

## 9.6 Main text (`research/text.py`)
```python
import trafilatura
from selectolax.parser import HTMLParser

def main_text(html: str, url: str) -> tuple[str, list[tuple[str, str]]]:
    text = trafilatura.extract(html, url=url, include_links=False, include_tables=True,
                               favor_recall=True, output_format="txt") or ""
    tree = HTMLParser(html)
    links = []
    for a in tree.css("a[href]"):
        links.append((a.attributes.get("href", ""), (a.text() or "").strip()[:80]))
    if len(text) < 400:                              # fallback: visible body text minus chrome
        for sel in ["script", "style", "noscript", "nav", "header", "footer", "svg"]:
            for n in tree.css(sel):
                n.decompose()
        body = tree.body.text(separator="\n") if tree.body else ""
        text = "\n".join(l.strip() for l in body.splitlines() if l.strip())
    return text[:20_000], links
```
- Store each page in `pages`: `url` (canonical), `business_id`, `fetched_at`, `http_status`, `render_mode`, `title`, `text` (max 20,000 characters), `text_hash` (sha256 of the text), `robots_allowed`.
- Upsert on `url`. If `text_hash` is unchanged since the last fetch, keep the old row and skip re-extraction for that page.

## 9.7 Structured data (`research/structured.py`)
- `extruct.extract(html, base_url=url, syntaxes=["json-ld", "microdata", "opengraph"], uniform=True)`.
- Keep items whose `@type` is one of: `LocalBusiness`, `MedicalClinic`, `MedicalBusiness`, `Dentist`, `Physician`, `RealEstateAgent`, `EducationalOrganization`, `School`, `Organization`, `Hotel`, `TravelAgency`, `AutoDealer`, `HealthAndBeautyBusiness`, `JobPosting`.
- Read `telephone`, `email`, `address`, `sameAs`, `openingHours`, `priceRange`, `numberOfEmployees`, `name`; from `JobPosting`: `title`, `datePosted`, `validThrough`, `hiringOrganization`.
- Turn them into facts **directly** (no AI): `field` = `jsonld_phone`, `jsonld_email`, `jsonld_name`, `jsonld_price_range`, `jsonld_employees`, `jsonld_job`; `quote` = the compact JSON fragment, `url` = the page URL, `model = 'code'`. These are **verified by code** in Step 10 by re-parsing the stored HTML (`verify_score = 100`).
- A `JobPosting` for a front-desk or builder role, posted within 30 days, also creates a `hiring_frontdesk` or `hiring_builder` signal (classified with `classify_signal`, as in 7.5.1).

## 9.8 Tech detection (`research/techstack.py`)
Search the raw HTML (including script `src` attributes and inline scripts) of every fetched page. All patterns must be verified at build against live sites, because vendors change their snippet URLs.

| Tool | Kind | Patterns (any match) |
|---|---|---|
| Practo widget | booking | `practo.com/widget`, `widget.practo.com`, `practo.com/embed` |
| Calendly | booking | `calendly.com` |
| Setmore | booking | `setmore.com` |
| Zoho Bookings | booking | `zohobookings`, `bookings.zoho` |
| Zoho SalesIQ | chat | `salesiq.zoho`, `zohopublic` with `salesiq` |
| Tawk.to | chat | `embed.tawk.to` |
| Intercom | chat | `widget.intercom.io`, `js.intercomcdn.com` |
| Freshchat | chat | `wchat.freshchat.com`, `fw-cdn.com` |
| Wati | WhatsApp vendor | `wati.io` |
| Interakt | WhatsApp vendor | `interakt.shop`, `interakt.ai` |
| Gallabox | WhatsApp vendor | `gallabox.com` |
| AiSensy | WhatsApp vendor | `aisensy.com` |
| WhatsApp link | WhatsApp | `wa.me/`, `api.whatsapp.com/send`, `whatsapp://send`, `web.whatsapp.com/send` |
| Meta Pixel | ads tag | `connect.facebook.net/` with `fbevents.js`, `fbq('init'` |
| Google Ads tag | ads tag | `AW-` followed by 9 to 11 digits in a gtag config |
| Google Analytics 4 | analytics | `gtag/js?id=G-` |
| Google Tag Manager | analytics | `googletagmanager.com/gtm.js` |
| Sell.do, LeadSquared, Meritto (NoPaperForms) | CRM | `sell.do`, `leadsquared`, `nopaperforms`, `meritto` |
| WordPress | CMS | `wp-content/`, `wp-includes/` |
| Wix | CMS | `static.wixstatic.com`, `wix.com` meta generator |
| Shopify | CMS | `cdn.shopify.com` |
| Webflow | CMS | `webflow.js`, `data-wf-site` |
| Squarespace | CMS | `squarespace.com` |
| GoDaddy builder | CMS | `img1.wsimg.com` |
| Next.js | framework | `/_next/static/` |

Outputs:
- A fact `field = 'tech_stack'`, `value` = list of `{tool, kind, page_url}`, `quote` = the first matched snippet (max 200 characters), `model = 'code'`, verified by code.
- **Derived for scoring (Step 11)**: `has_booking` (any booking tool, or a booking form found by the AI), `has_whatsapp` (WhatsApp link or WhatsApp vendor), `has_chat`, `pays_for_software` (any paid booking, chat, WhatsApp vendor or CRM tool), `runs_ads_tag` (Meta Pixel or Google Ads tag: a can-pay hint, **not** the manual `ads_running` signal), `free_builder` (Wix, GoDaddy builder, Google Sites, `business.site`).
- **Signal `no_booking`** (7.5.7): no booking tool, no WhatsApp, no chat on any fetched page, and the AI extraction (9.11) reports no booking method. Created in the morning run after extraction is collected.

## 9.9 Site quality (`research/quality.py`)
- PageSpeed Insights API v5: `GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={homepage}&strategy=mobile&category=performance&key={GOOGLE_MAPS_API_KEY}` (verify at build).
- Read `lighthouseResult.categories.performance.score` x 100. Store a fact `field = 'site_speed_mobile'`, `value` = the integer, `quote` = `"PageSpeed mobile {score}"`, `url` = homepage, `model = 'code'`.
- **Run it in the morning, not at night**, and only for businesses whose quick score after Step 10 is B or better (about 100 a day). Each call takes 15 to 40 seconds, so run 4 in parallel.
- `slow_site` signal (7.5.7) if the score is under 40.
- PageSpeed has a generous free daily quota with a key (verify at build). On quota errors, skip and retry tomorrow.

## 9.10 Practo enrichment (`clinics-in` only)
- `sources/practo.py` (Step 5) keeps an index of Practo **clinic profile URLs** for each city, built monthly from Practo's sitemaps (profile pages are allowed by robots.txt; search pages are not). Read Practo's terms before enabling (verify at build), and keep the kill switch `settings.sources_enabled.practo`.
- Match a queued clinic to a Practo profile: same city, `rapidfuzz.fuzz.token_set_ratio(match_key) >= 90`, and the locality in the Practo URL or page matches. No match means no Practo data (never guess).
- Fetch the profile page (1 request per 5 seconds, at most `practo.pages_per_day`, default 150). Store it as a `pages` row for the business.
- The AI extraction (9.11) receives the Practo page as one of its pages, so doctors count, fees, "Profile is claimed", rating and patient stories become **quoted facts** with the Practo URL. No separate parser is needed, though a small code parser for "Doctors (5)" and fee patterns is a useful cross-check.

## 9.11 Building the AI input (`pipeline/extract.py`, `build_items`)

### 9.11.1 What goes in
For each researched business, in this order (the most useful text first):
1. Homepage
2. Team or doctors page
3. Contact page
4. Careers page
5. Locations page
6. Pricing, services, courses or projects page
7. Booking page
8. About page
9. Practo profile (clinics in India)

Plus a short **context block** from facts already verified by code: tech stack, JSON-LD phones and emails, branch hints from Step 6. Its job is to stop the model wasting effort on those, not to be quoted.

### 9.11.2 Token budget
- Total input at most **16,000 tokens** per business (about 64,000 characters; use 4 characters per token as the estimate).
- Instructions and schema: about 2,000 tokens.
- Per-page budgets (tokens): home 3,000; team 2,500; contact 1,000; careers 2,000; locations 1,500; pricing 2,000; booking 800; about 1,500; Practo 1,500. Unused budget flows to the next page in order.

### 9.11.3 Trimming (before applying budgets)
1. **Repeated lines**: any line that appears on 3 or more pages of the same site is navigation or footer. Keep it once, on the homepage block only.
2. Remove cookie banners, "All rights reserved", social share text, newsletter boxes, and lines of only symbols or numbers.
3. **Keep-first lines**: inside each page's budget, keep first the lines containing a phone pattern, an email, `₹`, `Rs`, `AED`, `SAR`, a price, `Dr.`, `Doctor`, `Founder`, `Director`, `CEO`, `branch`, `centre`, `years`, `experience`, `book`, `appointment`, `WhatsApp`, `hiring`, `job`. Then fill with the rest in page order.
4. Cut each page at its budget on a line boundary.

### 9.11.4 Block format
Each page is wrapped so the model can cite the URL exactly:
```
### PAGE 3
URL: https://www.example.in/contact-us/
TEXT:
<trimmed text>
### END PAGE 3
```
The prompt (`prompts/extract_facts.md`, Step 4) tells the model that every `url` in its output **must be one of the URL lines** and every `quote` **must be copied exactly** from that page's TEXT.

## 9.12 The facts schema (`FactsExtraction`)
This is the exact JSON the model must return. It is passed as the structured-output schema (Gemini `response_schema`, OpenAI strict `json_schema`).

```python
# engine/src/nument_engine/models.py (extraction part)
from typing import Literal
from pydantic import BaseModel, Field

Currency = Literal["INR", "AED", "SAR", "QAR", "GBP", "SGD", "USD", "AUD"]

class Quoted(BaseModel):
    quote: str = Field(min_length=5, max_length=300, description="Exact text copied from the page TEXT")
    url: str = Field(description="Must be one of the PAGE URL lines in the input")

class PersonFact(Quoted):
    name: str
    role: str | None = None
    is_decision_maker: bool = Field(description="Owner, founder, director, CEO, managing partner, medical director")

class PhoneFact(Quoted):
    number: str
    label: str | None = Field(default=None, description="e.g. reception, WhatsApp, appointments, Dr. X")
    belongs_to: Literal["business", "person"]

class EmailFact(Quoted):
    email: str

class CountFact(Quoted):
    count: int = Field(ge=0)

class NameFact(Quoted):
    name: str

class PriceFact(Quoted):
    item: str
    amount: float = Field(ge=0)
    currency: Currency

class RoleFact(Quoted):
    title: str
    category: Literal["frontdesk", "builder", "other"]

class FlagFact(Quoted):
    value: bool

class TextFact(Quoted):
    value: str

class FactsExtraction(BaseModel):
    business_name: TextFact | None = None
    decision_makers: list[PersonFact] = Field(default_factory=list, max_length=5)
    phones: list[PhoneFact] = Field(default_factory=list, max_length=6)
    emails: list[EmailFact] = Field(default_factory=list, max_length=4)
    branches: CountFact | None = None
    staff_or_doctors: CountFact | None = None
    services: list[NameFact] = Field(default_factory=list, max_length=12)
    price_points: list[PriceFact] = Field(default_factory=list, max_length=10)
    booking_method: TextFact | None = Field(default=None, description="e.g. online form, call only, WhatsApp, Practo")
    whatsapp_present: FlagFact | None = None
    chat_widget: TextFact | None = None
    careers_roles: list[RoleFact] = Field(default_factory=list, max_length=10)
    in_house_tech: FlagFact | None = Field(default=None, description="True only if the page shows an in-house tech or IT team")
    is_agency_or_vendor: FlagFact | None = Field(default=None, description="True if they SELL software, marketing or IT services")
    languages: list[TextFact] = Field(default_factory=list, max_length=4)
    sales_notes: list[TextFact] = Field(default_factory=list, max_length=3,
                                         description="Quoted observations useful for a first message")
```

Rules stated in the prompt (and enforced again in Step 10):
- Not found means `null` or an empty list. **Never guess.** No fact without a quote.
- Copy quotes exactly (case and spacing as on the page), 5 to 300 characters.
- `is_decision_maker = true` only for owners, founders, directors, CEOs, managing partners, medical directors, principals.
- Prices only when an amount is written on the page.

## 9.13 Submitting the batch (night run)
```python
def submit(env, limit=None, dry_run=False, run_id=None) -> dict:
    biz = db.fetch_all(
        "select * from businesses where status='queued' and queued_at > now() - interval '1 day' "
        "order by queue_priority desc limit %s", (limit or 300,))
    items = []
    for b in biz:
        pages = load_pages_for(b["id"], fetched_since_hours=24)
        if not pages and not b["place_id"]:
            mark(b["id"], "rejected", "no_research_material")
            continue
        items.append({"custom_id": b["id"], "input": render_extract_prompt(b, pages)})
    if dry_run:
        return {"would_submit": len(items)}
    if not budget.guard("extract_facts", est_inr=estimate_batch_inr(items)):
        items = trim_to_budget(items)                    # highest priority first
    batch = llm.batch.submit(task="extract_facts", items=items, schema=FactsExtraction)
    db.execute(
        "insert into llm_batches (provider, provider_batch_id, task, status, item_count, submitted_at) "
        "values (%s, %s, 'extract_facts', 'submitted', %s, now())",
        (batch.provider, batch.id, len(items)))
    return {"submitted": len(items), "batch": batch.id}
```
- The provider and model come from `config/tasks.yaml` (Balanced tier: Gemini Flash in batch mode, about half price; verify the model id at build).
- One batch per night run. If there are more than 300 items (should not happen), split into several batches.

## 9.14 Collecting the batch (morning run)
1. Load `llm_batches` with `task = 'extract_facts'` and status `submitted` or `running`.
2. Poll the provider. If finished, download results. If not finished by **06:40 IST**, continue the morning run with whatever earlier batches finished, and collect this one in the next run. Businesses waiting on it stay `queued`.
3. For each result:
   - Validate against `FactsExtraction` with pydantic.
   - On a validation error, retry that single item **synchronously** once with the same model. If it fails again, set `reject_reason = 'extract_failed'`, keep the business `queued`, and count the error.
4. **Flatten into `facts` rows**, one row per item:

| Schema field | `facts.field` | `facts.value` |
|---|---|---|
| `business_name` | `business_name` | `{"name": ...}` |
| `decision_makers[]` | `decision_maker` | `{"name", "role", "is_decision_maker"}` |
| `phones[]` | `phone` | `{"number", "label", "belongs_to"}` |
| `emails[]` | `email` | `{"email"}` |
| `branches` | `branches` | `{"count"}` |
| `staff_or_doctors` | `staff_or_doctors` | `{"count"}` |
| `services[]` | `service` | `{"name"}` |
| `price_points[]` | `price_point` | `{"item", "amount", "currency"}` |
| `booking_method` | `booking_method` | `{"value"}` |
| `whatsapp_present` | `whatsapp_present` | `{"value"}` |
| `chat_widget` | `chat_widget` | `{"value"}` |
| `careers_roles[]` | `careers_role` | `{"title", "category"}` |
| `in_house_tech` | `in_house_tech` | `{"value"}` |
| `is_agency_or_vendor` | `is_agency_or_vendor` | `{"value"}` |
| `languages[]` | `language` | `{"value"}` |
| `sales_notes[]` | `sales_note` | `{"value"}` |

   Every row gets `quote`, `url`, `page_id` (looked up by canonical URL), `model` (the model id), `verified = false` (Step 10 decides), `created_at`.
5. Before inserting new facts, **delete that business's previous AI facts** (`model <> 'code'`) older than this run, so stale facts never mix with new ones. Code facts are replaced by their own step.
6. Set `businesses.status = 'researched'`, `researched_at = now()`.
7. Costs are logged by the router per batch (Step 4); add per-business averages to `runs.stats.extract`.

## 9.15 The research run (night)
```python
async def run_research(env, segment_ids=None, limit=None, dry_run=False, run_id=None) -> dict:
    queue = db.fetch_all(
        "select * from businesses where status='queued' and queued_at > now() - interval '1 day' "
        "order by queue_priority desc limit %s", (limit or 300,))
    sem = asyncio.Semaphore(8)                      # 8 hosts in parallel
    async def one(b):
        async with sem:
            if not b["website"]:
                return "no_website"
            pages = await crawl_site(b)             # 9.4 + 9.5, robots respected, stops on blocks
            for p in pages:
                save_page(b["id"], p, dry_run)       # 9.6
                save_structured_facts(b["id"], p, dry_run)   # 9.7
            save_tech_fact(b["id"], detect_tech(pages), dry_run)  # 9.8
            if b["segment_id"] == "clinics-in" and source_enabled("practo"):
                await practo_enrich(b, dry_run)      # 9.10
            return "ok"
    results = await asyncio.gather(*(one(b) for b in queue), return_exceptions=True)
    stats = Counter(r if isinstance(r, str) else "error" for r in results)
    save_stats(run_id, "research", dict(stats))
    return dict(stats)
```
Then the night run calls `extract.submit()` (9.13).

## 9.16 Time and cost budget (Balanced tier)
| Part | Per business | Per night (300) | Notes |
|---|---|---|---|
| Crawl (httpx, about 5 pages) | 0 ₹ | about 3 to 5 minutes | 8 hosts in parallel |
| Browser renders | 0 ₹ | at most 40, about 5 minutes | Only when needed |
| Practo pages | 0 ₹ | at most 150, slow rate | Clinics in India only |
| AI extraction (batch) | about ₹0.6 | about ₹185 | 16K in, 2K out, batch half price (verify prices) |
| PageSpeed (morning) | 0 ₹ | about 100, 4 in parallel | Only for B or better |

The night job's research and submission must finish within about 25 minutes (Step 14.6).

## 9.17 Storage hygiene
- `pages.text` is the biggest table. After 90 days, delete `pages` rows of `rejected` and `dormant` businesses, and keep `facts` (they hold the quotes). Step 18 schedules this.
- Never store full HTML in the database. Keep it in memory for tech detection and structured data, then drop it.

## 9.18 Pitfalls
- **Invented quotes**: models sometimes paraphrase. Step 10 drops any quote not found in the page text. Track the drop rate (target under 5%).
- **Wrong URL citation**: the model cites the homepage for a fact on the contact page. Step 10 checks the quote against all pages of that business and corrects the URL if it is found on another page.
- **Challenge pages**: Cloudflare and similar return a page that looks like content. The challenge markers in 9.5 catch them; never try to pass them.
- **Bad TLS**: many small Indian sites have broken certificates. The single `http://` fallback is allowed; do not disable certificate checks on `https://`.
- **Huge pages** (long blog homepages): the 3 MB body cap and the page budgets keep the input small.
- **Practo false matches**: require both the name ratio and the locality match. A wrong Practo match puts another clinic's doctors and fees in the lead.
- **Batch delays**: batches can take hours. The 06:40 cut-off keeps the morning run on time; late items flow into the next morning.
- **Duplicate pages**: `/contact` and `/contact/` and `?utm=` variants. Always canonicalise URLs (7.4.3) before fetching and storing.

## 9.19 Done when
- [ ] Unit tests: page choice (fixtures of 5 real sites), main text extraction, JSON-LD facts, every tech pattern in 9.8 (one fixture each), the budget trimmer, `FactsExtraction` validation and the flattening table.
- [ ] `nlead research --env dev --limit 20` crawls 20 queued businesses, respects robots (a disallowed test host is skipped), and stores `pages` and code facts.
- [ ] `nlead extract submit --env dev --limit 20` submits one batch and writes an `llm_batches` row; `nlead extract collect` writes facts for at least 18 of 20.
- [ ] Every AI fact row has a non-empty `quote` and a `url` that belongs to that business's pages.
- [ ] Spot check of 5 businesses: the facts match what a person reads on the site (decision maker, phone, branches, booking method).
- [ ] No request went to linkedin.com, x.com, twitter.com or instagram.com, and no CAPTCHA or challenge page was ever submitted.
- [ ] The night research plus submit for 300 businesses finishes in under 25 minutes on a GitHub Actions runner.
- [ ] Cost per researched business in `costs` is within 30% of the estimate in 9.16.

---

---

# Step 10: Verification

**Goal:** before anything is scored or written, prove every fact again **with code, not AI**. A fact that cannot be proven is kept for audit but never used. Then check that each phone number is real and allowed, that the website is alive, that the business is not a competitor, and that its signals are still fresh.

**Needs first:** Step 2 (tables `facts`, `contacts`, `pages`, `businesses`, `signals`, `suppression`), Step 4 (AI router, task `verify_flagged`), Step 9 (pages fetched and stored in `pages.text`, facts extracted into `facts` with `quote`, `url`, `page_id`).

**Runs in:** the morning run (`nlead verify`), right after `nlead extract collect`.

**File:** `engine/src/nument_engine/pipeline/verify.py`

---

## 10.1 What verification produces

| Output | Where it is written | Used by |
|---|---|---|
| `facts.verified`, `facts.verify_score`, `facts.verified_at` on every fact | `facts` | Scoring (Step 11), messages (Step 12), app "Facts" panel |
| One row per usable phone or email, with type and owner | `contacts` | Reach score, WhatsApp link, app contact card |
| Website status fact (`field = 'website_status'`) | `facts` (model `rule`) | Can-pay (custom website), rejection of dead sites |
| Rejection with a reason | `businesses.status = 'rejected'`, `businesses.reject_reason` | Keeps competitors and dead businesses out |
| Suppression | `businesses.status = 'suppressed'`, `contacts.do_not_contact = true` | Never contacted again |
| Conflict resolution | Losing fact gets `verified = false`, `verify_score = -1` | Clean single truth per field |
| Status `researched` | `businesses.status` | Step 11 picks these up |

Order inside `verify_business(business_id)`:
1. Quote verification (10.2)
2. Website status (10.4)
3. Competitor and agency check (10.5)
4. Suppression check (10.3.6)
5. Phones and emails into `contacts` (10.3)
6. Conflict detection and `verify_flagged` (10.7)
7. Signal freshness (10.6)
8. Final status (10.8)

Each sub-step is idempotent: running `nlead verify` twice gives the same rows.

---

## 10.2 Quote verification

### 10.2.1 The rule
A fact is **verified** only if its `quote` can be found again in the stored text of the page it came from (`pages.text` of `facts.page_id`, or of the page whose `url` equals `facts.url`). The AI that extracted the fact is never asked whether it is true. Code checks it.

### 10.2.2 Normalisation (both quote and page text)
Apply the same function to both strings before comparing:

1. Unicode NFKC normalise (turns fancy quotes, non-breaking spaces and full-width digits into plain ones).
2. Lowercase.
3. Replace every run of whitespace (spaces, tabs, newlines, non-breaking spaces) with one space.
4. Replace typographic quotes and apostrophes (`‘ ’ “ ” ´`) with plain `'` and `"`.
5. Remove characters that are not letters, digits, spaces or these: `@ . + / : % ₹ $ &`. This keeps phone numbers, emails, prices and URLs comparable.
6. Strip leading and trailing spaces.

```python
# engine/src/nument_engine/pipeline/verify.py
import re
import unicodedata
from rapidfuzz import fuzz

_WS = re.compile(r"\s+")
_KEEP = re.compile(r"[^\w\s@.+/:%₹$&]", re.UNICODE)
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "´": "'"})

def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_QUOTES).lower()
    t = _KEEP.sub(" ", t)
    return _WS.sub(" ", t).strip()
```

### 10.2.3 Matching algorithm
For each fact with a non-empty `quote`:

1. `q = norm(fact.quote)`, `p = norm(page.text)`.
2. If `len(q) < 8`: too short to prove anything. Set `verified = false`, `verify_score = 0`, reason `quote_too_short`. (Exception: a phone or email fact whose quote is the number or address itself is checked by 10.3 instead.)
3. **Exact pass:** if `q in p`, set `verify_score = 100`, `verified = true`.
4. **Fuzzy pass:** otherwise compute `score = fuzz.partial_ratio(q, p)` (rapidfuzz). This finds the best matching window of the page for the quote, so small differences (a dropped comma, a line break inside a phone number) still match.
5. If `score >= 92`: `verified = true`, `verify_score = score`.
6. If `score < 92`: `verified = false`, `verify_score = score`, reason `quote_not_found`.
7. Write `verified_at = now()` in every case.

Performance: page texts are capped at 20,000 characters (Step 9), so `partial_ratio` is fast. For very long pages, first narrow the page to a 2,000 character window around the best `fuzz.partial_ratio_alignment` hit, then score that window.

```python
from datetime import datetime, timezone
from rapidfuzz.fuzz import partial_ratio

QUOTE_MIN_LEN = 8
QUOTE_THRESHOLD = 92

def check_quote(quote: str, page_text: str) -> tuple[bool, int, str]:
    q, p = norm(quote), norm(page_text)
    if len(q) < QUOTE_MIN_LEN:
        return False, 0, "quote_too_short"
    if q in p:
        return True, 100, "exact"
    score = int(partial_ratio(q, p))
    if score >= QUOTE_THRESHOLD:
        return True, score, "fuzzy"
    return False, score, "quote_not_found"

def verify_facts(conn, business_id: str) -> dict:
    rows = conn.execute(
        """select f.id, f.field, f.quote, coalesce(p.text, p2.text) as page_text
             from facts f
             left join pages p  on p.id = f.page_id
             left join pages p2 on p2.url = f.url and p2.business_id = f.business_id
            where f.business_id = %s and f.model <> 'rule'""",
        (business_id,),
    ).fetchall()
    stats = {"verified": 0, "unverified": 0, "no_page": 0}
    for fid, field, quote, page_text in rows:
        if page_text is None:
            ok, score, why = False, 0, "page_missing"
            stats["no_page"] += 1
        else:
            ok, score, why = check_quote(quote or "", page_text)
        conn.execute(
            "update facts set verified = %s, verify_score = %s, verified_at = %s where id = %s",
            (ok, score, datetime.now(timezone.utc), fid),
        )
        stats["verified" if ok else "unverified"] += 1
    return stats
```

### 10.2.4 What happens to unverified facts
- They stay in `facts` (audit trail, golden-set evaluation, app "Unverified" tab for admins).
- Scoring (Step 11) and message writing (Step 12) **only ever read `facts where verified = true`**. Put this filter in one shared SQL view so nobody forgets it:

```sql
create or replace view v_verified_facts as
select * from facts where verified = true and coalesce(verify_score, 0) >= 0;
```

- If more than 40% of a business's extracted facts fail verification, mark the extraction as suspicious: write an activity on the business log (`activities` is lead-scoped, so use `runs.stats` for the batch count) and re-queue the business for research once with `render_mode = 'browser'`, because the page text was probably incomplete.

### 10.2.5 Pitfalls
- **Do not verify against the AI's own output.** Always against `pages.text` stored by Step 9.
- **Do not lower the threshold to rescue facts.** 92 was chosen so that genuine quotes with small formatting changes pass, while paraphrases fail. If many real quotes fail, the fix is in Step 9 page text extraction, not here.
- **Prices and numbers:** the normaliser keeps `₹`, `$`, digits, `.` and `/`, so "₹1,500" becomes "₹1 500" on both sides. Never strip digits.

---

## 10.3 Phones and emails

### 10.3.1 Sources of phone numbers, in priority order
| Priority | Source | `contacts.source` | Allowed? |
|---|---|---|---|
| 1 | The business's own website (verified fact `phone`, or `tel:` / `wa.me` links found in the page HTML) | `website` | Yes |
| 2 | Official registry entry for the business (for example the ART registry email) | `registry` | Yes |
| 3 | The business's own Google listing (Places Details, fetched within the last 30 days) | `google_listing` | Yes, as a fallback, shown as "from Google listing" |
| 4 | Anything else (directories, data brokers, social profiles, guessed numbers) | none | **Never** |

### 10.3.2 Parsing and typing with `phonenumbers`
For each candidate number:

1. Parse with the segment's country as the default region (`IN` for `*-in`, `AE` for `*-ae`): `phonenumbers.parse(raw, region)`.
2. Reject if `not phonenumbers.is_valid_number(n)`.
3. Format to E.164: `phonenumbers.format_number(n, PhoneNumberFormat.E164)`, for example `+919876543210`.
4. Map the type:

| `phonenumbers.number_type(n)` | `contacts.phone_type` |
|---|---|
| `MOBILE` | `mobile` |
| `FIXED_LINE` | `landline` |
| `FIXED_LINE_OR_MOBILE` | check the national prefix: India 6, 7, 8, 9 start = `mobile`, else `landline`; UAE `5x` = `mobile` |
| `TOLL_FREE`, `SHARED_COST` | `tollfree` |
| anything else | `unknown` |

5. Extra India rule ported from the old engine (`phone_kind` in `lead-engine/scripts/check_links_emails.py`): if the raw text shows an STD code in brackets or with a leading 0 and a separator, for example `(080) 4123 4567` or `022-2345 6789`, it is a **landline** even if the digits after the code start with 6 to 9.

```python
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType as T

STD_LANDLINE = re.compile(r"^\s*(?:\+91[\s-]*)?\(?0?\d{2,4}\)[\s-]|^\s*0\d{2,4}[\s-]+\d{6,8}\s*$")

def parse_phone(raw: str, region: str) -> tuple[str, str] | None:
    try:
        n = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(n):
        return None
    e164 = phonenumbers.format_number(n, PhoneNumberFormat.E164)
    t = phonenumbers.number_type(n)
    if region == "IN" and STD_LANDLINE.search(raw or ""):
        return e164, "landline"
    if t == T.MOBILE:
        return e164, "mobile"
    if t == T.FIXED_LINE:
        return e164, "landline"
    if t == T.FIXED_LINE_OR_MOBILE:
        national = str(n.national_number)
        if region == "IN":
            return e164, "mobile" if national[:1] in "6789" else "landline"
        if region == "AE":
            return e164, "mobile" if national.startswith("5") else "landline"
        return e164, "unknown"
    if t in (T.TOLL_FREE, T.SHARED_COST):
        return e164, "tollfree"
    return e164, "unknown"
```

### 10.3.3 "Found on their own page" check
A phone with `source = 'website'` is **verified** only if the national digits appear on a stored page of the business's own `web_domain`:

1. Collect all pages of the business where `pages.url` host ends with `businesses.web_domain`.
2. Extract every number from page text and from `tel:` / `wa.me` / `api.whatsapp.com/send?phone=` links (ported regexes `PHONE_RUN` and `PHONE_LINK` from the old `check_links_emails.py`).
3. Parse each with `parse_phone` and compare E.164 values.
4. Match found: `contacts.verified = true`, `source_url` = that page URL, `quote` = the 40 characters around the number.
5. No match: the fact is ignored (it may be a number from a third-party widget or a different business).

### 10.3.4 Google listing fallback
Only when no verified `website` phone exists:
1. Use `nationalPhoneNumber` / `internationalPhoneNumber` from the Places Details fetched in Step 6, only if `businesses.places_fetched_at` is within the last 30 days.
2. Insert a contact with `source = 'google_listing'`, `source_url` = `https://www.google.com/maps/place/?q=place_id:{place_id}`, `quote` = null, `verified = true`.
3. The app and sheet show the label **"from Google listing"** next to this number.
4. Places terms (A.4.4): this contact must be refreshed within 30 days. The monthly job (Step 14) deletes `google_listing` contacts older than 30 days that were not refreshed. Track the age with `contacts.verified_at` (see the note at the end of this step).

### 10.3.5 Emails
1. Accept emails from verified `email` facts and from `mailto:` links on own-domain pages.
2. Decode obfuscations found in registries and pages: `[at]`, `(at)`, ` at ` and `[dot]`, `(dot)`, ` dot `.
3. Validate the shape with the ported `EMAIL_RE`.
4. Domain must have an MX record (use `dnspython`, cached for 7 days). No SMTP probing: it is intrusive and can get our IP flagged.
5. Free-mail addresses (gmail.com and similar) are allowed for small businesses but get a lower trust note in `contacts.role` ("free mail").

### 10.3.6 Suppression
Before writing any contact:
1. Look up `suppression` by `phone_e164`, by `email` (lowercase) and by `businesses.web_domain`.
2. Any hit on the domain: set `businesses.status = 'suppressed'`, stop verifying this business.
3. Any hit on a phone or email: insert the contact with `do_not_contact = true` (so the app explains why) and never use it for reach.

### 10.3.7 Decision maker detection
A contact is `is_decision_maker = true` when:
- a verified fact `decision_maker` exists with a role matching (case-insensitive): `founder`, `co-founder`, `owner`, `proprietor`, `director`, `managing director`, `md`, `ceo`, `principal`, `medical director`, `chief`, `partner`, `head` (and for clinics, a doctor named as the clinic's founder or head), **and**
- either the phone or email is printed next to that name (the person's name appears within 120 characters of the number in the same page text), or the contact is that person's own email (name parts in the local part).

Write the person's `name` and `role` on the contact. If a decision maker is known but has no own number, create a contact row with `name`, `role` and no phone, so the greeting can use the name while reach uses the business number.

### 10.3.8 Contacts write
Upsert into `contacts` keyed on (`business_id`, `phone_e164`) for phones and (`business_id`, `email`) for emails. Never delete a contact that a person edited in the app (rows edited by users carry an `activities` entry; check before overwriting).

---

## 10.4 Website status

### 10.4.1 States
| `website_status` value | Meaning | Effect |
|---|---|---|
| `live` | Home page loads (2xx or 3xx) with real content | Normal |
| `parked` | Domain for sale, parked or suspended page | No custom-website points; research quality drops |
| `coming_soon` | Under construction or launching soon | Treated as a growth hint (they are setting up) |
| `dead` | DNS failure, repeated connection errors, or 404/410 on the home page | Reject if no other usable contact |
| `blocked` | 401, 403, 429, 503 or a bot-check page | Unknown; never treated as dead |
| `unknown` | Timeout or TLS problem | Retry next run; never treated as dead |

### 10.4.2 Detection (ported from the old engine)
Use the home page row in `pages` (Step 9 already fetched it). Port these from `lead-engine/scripts/check_links_emails.py`:

```python
PARKED = re.compile(
    r"domain (?:is|may be) for sale|buy this domain|this domain is parked|parked free|"
    r"sedoparking|hugedomains|dan\.com/buy|domain has expired|godaddy\.com/domainsearch|"
    r"account suspended|site not found|404 not found", re.I)
COMING_SOON = re.compile(r"coming soon|under construction|launching soon", re.I)

def website_status(http_status: int | None, text: str, error: str | None) -> str:
    if error and re.search(r"timed out|timeout|temporarily unavailable|connection reset|remote end closed", error, re.I):
        return "unknown"
    if error and "CERTIFICATE_VERIFY_FAILED" in error:
        return "unknown"  # often local network interception, never proof of death
    if error:
        return "dead"
    if http_status in (401, 403, 429, 503) or re.search(r"cloudflare|captcha|access denied", (text or "")[:5000], re.I):
        return "blocked"
    if http_status is None or http_status >= 400:
        return "dead" if http_status in (404, 410) else "unknown"
    if PARKED.search(text or ""):
        return "parked"
    if COMING_SOON.search((text or "")[:20000]):
        return "coming_soon"
    return "live"
```

### 10.4.3 Writing it
Insert or update one fact: `field = 'website_status'`, `value = {"status": "live"}`, `quote` = the HTTP status line or the matched parked phrase, `url` = home page, `model = 'rule'`, `verified = true`, `verify_score = 100`. Code-derived facts use `model = 'rule'` so they are never re-checked by 10.2.

### 10.4.4 Rules
- `dead` twice in a row on two different days and no verified contact: `businesses.status = 'rejected'`, `reject_reason = 'website_dead_no_contact'`.
- `dead` but a verified Google listing phone exists: keep the business, no custom-website points.
- Never reject on `blocked` or `unknown`.

---

## 10.5 Competitor and agency check

### 10.5.1 Why
Agencies, IT service firms, software vendors and staffing firms are competitors, not buyers. Old runs found that job posts made under a person's name were agencies 5 times out of 5.

### 10.5.2 Signals of a competitor (any one is enough to flag, two to reject)
1. Verified fact `is_agency_or_vendor = true` from extraction (Step 9 asks the AI to quote the line that shows it).
2. Own-site text matches (case-insensitive) any of: `web development company`, `software development company`, `app development company`, `digital marketing agency`, `it services`, `it solutions`, `we build websites`, `website design company`, `staffing solutions`, `recruitment agency`, `outsourcing partner`, `white label`.
3. `web_domain` or name matches `engine/config/exclusions.yaml` under `competitors:`.
4. The business's services list (verified facts) is mainly software, marketing or hiring services.

### 10.5.3 Outcome
- Two or more matches: `businesses.status = 'rejected'`, `reject_reason = 'competitor'`.
- Exactly one match: send to `verify_flagged` (10.7) with the question "Is this business an agency or software vendor that sells the same services as Nument?" and follow its answer.
- Big chains and hospitals in `exclusions.yaml` under `big_chains:` and `hospitals:`: `reject_reason = 'big_chain'` or `'hospital'`.

---

## 10.6 Signal freshness

1. For every signal of the business: active if `now() < expires_at`.
2. Expired signals stay in the table (history) but are ignored by scoring.
3. If the business's only reason to be in the queue was a signal that expired before research finished, it is still scored (it may qualify as `fit_only`).
4. For `hiring_*` signals from job boards: if the job page now shows "closed", "no longer accepting applications" or an apply-by date in the past (Step 7 records `details.apply_by`), set `expires_at = now()`.
5. **Phone freshness:** before a lead can enter the sheet, the page that proves the phone must have been fetched in the last 14 days. If older, re-fetch that single page now (cheap HTTP) and re-run 10.3.3 for it.

---

## 10.7 Conflict detection and `verify_flagged`

### 10.7.1 What counts as a conflict
After quote verification, look for verified facts that disagree:

| Field | Conflict when |
|---|---|
| `decision_maker` | Two different people both claimed as founder or owner |
| `branches` | Two values that differ by more than 1 |
| `staff_or_doctors` | Two values that differ by more than 30% |
| `is_agency_or_vendor` | One fact says yes, another says no |
| `in_house_tech` | One says yes, one says no |
| `booking_method` | One says online booking exists, the site scan says none |

### 10.7.2 Resolution
1. Rule first: prefer the fact from the more specific page (team page beats home page; contact page beats footer), then the most recent page.
2. If the rule cannot decide, call the AI task `verify_flagged` (Gemini 3 Flash on the Balanced tier) with: the field, the conflicting facts with their quotes and URLs, and up to 1,500 characters of context around each quote. The model must answer with the id of the fact it trusts, or `none`, and one sentence of reasoning.
3. Winner keeps `verified = true`. Losers get `verified = false`, `verify_score = -1` (meaning "lost a conflict").
4. `none`: both losers. The field is treated as unknown.
5. Budget: `verify_flagged` runs only on flagged businesses (about 15% of a day). Each call is about 4K tokens in, 0.5K out.

```python
# Output schema for verify_flagged (pydantic, enforced as JSON schema by the router)
from pydantic import BaseModel, Field

class FlaggedVerification(BaseModel):
    trusted_fact_id: str | None = Field(description="id of the fact to keep, or null if none can be trusted")
    is_competitor: bool | None = Field(default=None, description="only for the agency question")
    reason: str = Field(max_length=240)
```

---

## 10.8 Final status after verification

| Situation | `businesses.status` | `reject_reason` |
|---|---|---|
| Domain suppressed | `suppressed` | `suppressed` |
| Competitor | `rejected` | `competitor` |
| Big chain or hospital | `rejected` | `big_chain` / `hospital` |
| No usable contact of any kind (no phone, email or form) | `rejected` | `no_contact` |
| Dead website twice and no contact | `rejected` | `website_dead_no_contact` |
| Everything else | `researched` | null |

Set `businesses.researched_at = now()` for every business that reached `researched`.

```python
def verify_business(conn, business_id: str, segment, run_id: str) -> str:
    verify_facts(conn, business_id)
    status = check_website(conn, business_id)
    if is_suppressed(conn, business_id):
        return set_status(conn, business_id, "suppressed", "suppressed")
    comp = competitor_matches(conn, business_id, segment)
    if comp >= 2:
        return set_status(conn, business_id, "rejected", "competitor")
    if comp == 1 and flagged_is_competitor(conn, business_id, run_id):
        return set_status(conn, business_id, "rejected", "competitor")
    write_contacts(conn, business_id, segment)
    resolve_conflicts(conn, business_id, run_id)
    refresh_signal_freshness(conn, business_id)
    if not has_usable_contact(conn, business_id):
        return set_status(conn, business_id, "rejected", "no_contact")
    return set_status(conn, business_id, "researched", None)
```

## 10.9 Done when
- [ ] `nlead verify --env dev --limit 50` runs without errors and is idempotent (second run changes nothing).
- [ ] Every fact of the 50 businesses has `verified`, `verify_score` and `verified_at` set.
- [ ] A hand check of 20 random verified facts finds the quote on the page every time.
- [ ] A hand check of 20 random unverified facts shows real problems (paraphrase or wrong page), not formatting.
- [ ] `v_verified_facts` exists and Steps 11 and 12 read only from it.
- [ ] Indian landlines written as `(080) 4123 4567` are typed `landline`; UAE `+971 5x` numbers are `mobile`.
- [ ] No contact has a source other than `website`, `registry` or `google_listing`.
- [ ] Google listing contacts show the label "from Google listing" in the app and sheet, and the monthly cleanup removes ones older than 30 days.
- [ ] A suppressed domain, phone and email in the dev data are never used.
- [ ] Three known agencies seeded into dev are rejected with `competitor`.
- [ ] Parked, coming-soon, dead and blocked test pages get the right `website_status`.

> **Names this step needs that are not yet in A.12:** `contacts.verified_at` (timestamp, for the 30-day Google listing rule). Add it in Step 2's migration.

---

---

# Step 11: Scoring and grading

**Goal:** turn verified facts and active signals into one number from 0 to 100, a grade (A to D), a pitch mode, an angle and a test group. Then let the top model review the best half, and create or update the lead rows.

**Needs first:** Step 10 (verified facts, contacts, statuses), Step 3 (segment YAML with `fit`, `can_pay`, `ticket_class`, `angles`), Step 4 (router, task `judge_lead`).

**Runs in:** morning run, after verify: `nlead score` then `nlead judge`.

**Files:** `engine/src/nument_engine/pipeline/score.py`, `engine/src/nument_engine/pipeline/judge.py`

---

## 11.1 Score anatomy

```
raw   = fit_bonus (0, 5 or 10) + can_pay (0 to 30) + intent (0 to 40)        -> 0 to 80
total = round( raw / 80 * 100 * reach )                                      -> 0 to 100
grade = A if total >= 70, B if 55 to 69, C if 40 to 54, D if under 40 (A.12.9)
```

If the fit gate fails (`fit < 2`), the grade is **D** regardless of the other numbers, with reason `fit_gate`.

All weights live in YAML so they can be tuned without code changes:
- defaults in `engine/config/scoring.yaml`,
- per-segment overrides under `scoring:` in `engine/segments/{segment}.yaml`.

`SCORE_VERSION = "s1.0"` is a constant in `score.py` and is written to `scores.version`. Any change to formulas or default weights bumps it (`s1.1`, `s2.0`). Changing only a segment YAML value does not bump the version, but the YAML copy is saved in `segments.config`, so every score is traceable.

---

## 11.2 Fit gate (0 to 3)

| Point | Rule | Data used |
|---|---|---|
| +1 type match | `businesses.category` or `subcategory` is in `segment.fit.categories`, or a verified `services` fact matches `segment.fit.service_keywords` | businesses, facts |
| +1 size | any of: `review_count >= fit.min_reviews` (default 100), `staff_count >= fit.min_staff` (default 2), `branches_count >= 2` | businesses (filled from verified facts and Places) |
| +1 owner-led, no tech team | **no** verified `in_house_tech = yes` fact **and** not on `exclusions.yaml` lists. Unknown counts as yes (most small businesses never publish this) | facts, exclusions |

`fit_bonus = 10 if fit == 3 else 5 if fit == 2 else 0`. `fit < 2` means grade D.

---

## 11.3 Can-pay points (0 to 30)

Defaults (segments override any number):

| Proxy | Rule | Points |
|---|---|---|
| Branches | `branches_count >= 2` | +6 |
| | `branches_count >= 4` | +8 (instead of 6) |
| Staff (doctors, agents, teachers, stylists) | `staff_count >= 3` | +4 |
| | `staff_count >= 8` | +6 (instead of 4) |
| Reviews (a busy front desk) | `review_count >= 100` | +4 |
| | `review_count >= 300` | +6 (instead of 4) |
| Premium price evidence | any verified `price_point` at or above `can_pay.premium_price` for the segment | +5 |
| Already pays for software | tech scan (Step 9.4) found a booking system, CRM, live chat, a WhatsApp Business API provider (Wati, Interakt, Gallabox, AiSensy) or a claimed Practo profile | +3 |
| Custom website | `website_status = live`, own domain, not a free builder sub-domain | +2 |
| Ticket class | `ticket_class[subcategory]` from the segment YAML, 0 to 6 | +0 to +6 |
| Money signal | an active `funding` signal | +6 |

`can_pay = min(sum, 30)`.

Premium price thresholds (defaults, per segment YAML `can_pay.premium_price`):

| Segment | Premium price evidence |
|---|---|
| `clinics-in` | consultation `>= ₹800`, or any treatment or package `>= ₹20,000` |
| `clinics-ae` | consultation `>= AED 300`, or any treatment `>= AED 3,000` |
| `realestate-in` | any listed property `>= ₹75 lakh` |
| `realestate-ae` | any listed property `>= AED 1.5 million` |
| `education-in` | any course or programme fee `>= ₹50,000` |
| `education-ae` | any course fee `>= AED 10,000` |

Ticket class examples (per segment YAML `ticket_class`):

| Segment | Subcategory | Points |
|---|---|---|
| clinics | ivf_fertility | 6 |
| clinics | aesthetic, hair_transplant | 5 |
| clinics | dermatology | 4 |
| clinics | dental_chain | 3 |
| clinics | physio, therapy_group | 2 |
| realestate | developer | 6 |
| realestate | broker_large (10+ agents) | 4 |
| realestate | broker | 2 |
| education | study_abroad | 5 |
| education | coaching_institute | 4 |
| education | academy | 3 |

---

## 11.4 Intent points (0 to 40)

### 11.4.1 Per signal
For each **active** signal (`now() < expires_at`), with `window = expires_at - observed_at` and `age = now() - observed_at`:

```
ratio = age / window
decay = 1.0 if ratio <= 0.30
        0.7 if ratio <= 0.60
        0.4 if ratio <= 1.00
        0.0 otherwise
value = signals.points * decay
```

`signals.points` comes from A.12.3 (possibly overridden per segment). `funding` has 0 intent points (it adds can-pay instead).

### 11.4.2 Combine
1. **One value per type:** keep only the highest `value` per `signals.type`. Five job posts for receptionists count once.
2. **Independent events only:** if two signals of different types share `details.event_key` (for example a news article and a careers page about the same new branch), count only the higher one.
3. `base = sum of the kept values`.
4. **Stacking bonus:** `n = number of kept types with value > 0`. `bonus = min(2 * (n - 1), 4)` when `n >= 2`, else 0.
5. `intent = min(base + bonus, 40)`.

---

## 11.5 Reach multiplier (0 to 1)

Pick the best usable contact (not `do_not_contact`, verified):

| Best contact | `reach` |
|---|---|
| Decision maker's own mobile (`is_decision_maker = true`, `phone_type = mobile`, source `website`) | 1.00 |
| Business mobile (`mobile`, source `website` or `google_listing`) | 0.85 |
| Landline only | 0.65 |
| Email only | 0.45 |
| Contact form only (verified fact `contact_form_url`) | 0.30 |
| Nothing | 0.00 (already rejected in Step 10) |

---

## 11.6 Code

```python
# engine/src/nument_engine/pipeline/score.py
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCORE_VERSION = "s1.0"
GRADE_A, GRADE_B, GRADE_C = 70, 55, 40

@dataclass
class ScoreResult:
    fit: int
    can_pay: int
    intent: float
    reach: float
    total: int
    grade: str
    pitch_mode: str
    angle: str
    reasons: dict = field(default_factory=dict)

def decay(observed_at: datetime, expires_at: datetime, now: datetime) -> float:
    window = (expires_at - observed_at).total_seconds()
    if window <= 0 or now >= expires_at:
        return 0.0
    ratio = (now - observed_at).total_seconds() / window
    return 1.0 if ratio <= 0.30 else 0.7 if ratio <= 0.60 else 0.4 if ratio <= 1.0 else 0.0

def intent_score(signals: list[dict], now: datetime) -> tuple[float, list[dict]]:
    best_by_type: dict[str, dict] = {}
    for s in signals:
        v = s["points"] * decay(s["observed_at"], s["expires_at"], now)
        if v <= 0:
            continue
        cur = best_by_type.get(s["type"])
        if cur is None or v > cur["value"]:
            best_by_type[s["type"]] = {**s, "value": v}
    by_event: dict[str, dict] = {}
    for s in best_by_type.values():
        key = (s.get("details") or {}).get("event_key") or f"type:{s['type']}"
        if key not in by_event or s["value"] > by_event[key]["value"]:
            by_event[key] = s
    kept = list(by_event.values())
    base = sum(s["value"] for s in kept)
    n = len(kept)
    bonus = min(2 * (n - 1), 4) if n >= 2 else 0
    return min(base + bonus, 40.0), kept

def grade_of(total: int) -> str:
    return "A" if total >= GRADE_A else "B" if total >= GRADE_B else "C" if total >= GRADE_C else "D"

def score_business(b: dict, facts: list[dict], signals: list[dict], contacts: list[dict], seg) -> ScoreResult:
    now = datetime.now(timezone.utc)
    fit, fit_why = fit_gate(b, facts, seg)
    can_pay, pay_why = can_pay_points(b, facts, signals, seg)
    intent, kept = intent_score([s for s in signals if s["category"] != "money"], now)
    reach, reach_why = reach_of(contacts)
    fit_bonus = 10 if fit == 3 else 5 if fit == 2 else 0
    raw = fit_bonus + can_pay + intent
    total = round(raw / 80 * 100 * reach)
    grade = "D" if fit < 2 else grade_of(total)
    mode = pitch_mode_of(kept)
    angle = pick_angle(mode, kept, facts, seg)
    reasons = {"fit": fit_why, "can_pay": pay_why, "intent": [
        {"signal_id": s["id"], "type": s["type"], "value": round(s["value"], 1)} for s in kept],
        "reach": reach_why, "fit_gate_failed": fit < 2}
    return ScoreResult(fit, can_pay, round(intent, 1), reach, total, grade, mode, angle, reasons)
```

`fit_gate`, `can_pay_points` and `reach_of` each return `(value, reasons)`, where `reasons` is a list of short strings with the fact or signal ids used, for example `["branches_count=3 (fact 8f2c)", "review_count=410 (places)"]`. These reasons power the app's "Why this score" panel.

---

## 11.7 Worked examples

### 11.7.1 IVF clinic in Pune (clinics-in)
- Fit: type match (+1), 420 reviews (+1), no tech team (+1) = 3, so `fit_bonus = 10`.
- Can-pay: 2 branches (+6), 5 doctors (+4), 420 reviews (+6), IVF package ₹1.6 lakh (+5), Practo profile claimed (+3), custom site (+2), ticket ivf_fertility (+6) = 32, capped to **30**.
- Intent: `hiring_frontdesk` 8 points, 5 days old of 30 (ratio 0.17, decay 1.0) = 8.0. `review_pain` 6 points, 40 days of 90 (ratio 0.44, decay 0.7) = 4.2. Two types, bonus +2. Intent = **14.2**.
- Reach: business mobile = 0.85.
- `raw = 10 + 30 + 14.2 = 54.2`, `total = round(54.2 / 80 * 100 * 0.85) = round(57.6) = 58` = **B**.
- Pitch mode `visible_pain`, angle `frontdesk_load`, test group `clinics-in:visible_pain:frontdesk_load`.

### 11.7.2 Real estate developer in Gurugram (realestate-in) with a stated need
- Fit 3, `fit_bonus = 10`.
- Can-pay: 4 project sites counted as branches (+8), 12 staff (+6), projects from ₹1.2 crore (+5), CRM detected (+3), custom site (+2), developer (+6) = 30.
- Intent: `public_ask` 10 points, 3 days of 14 (ratio 0.21, decay 1.0) = 10. `hiring_frontdesk` (telecallers) 8, 12 days of 30 (ratio 0.4, decay 0.7) = 5.6. `ads_running` 4, decay 1.0 = 4. Three types, bonus +4. Intent = **23.6**.
- Reach: the founder's own mobile on the contact page = 1.0.
- `raw = 10 + 30 + 23.6 = 63.6`, `total = round(63.6 / 80 * 100 * 1.0) = 80` = **A**.
- Pitch mode `stated_need` (a public ask is active), angle `build_what_they_asked`.

### 11.7.3 Coaching institute in Bengaluru (education-in), fit only
- Fit 2 (type match and size, but a verified "our tech team" line), `fit_bonus = 5`.
- Can-pay: 150 reviews (+4), course fee ₹65,000 (+5), coaching_institute (+4) = 13.
- Intent: no active signals = 0.
- Reach: landline only = 0.65.
- `raw = 18`, `total = round(18 / 80 * 100 * 0.65) = 15` = **D**. Not a lead. Re-checked in 90 days.

### 11.7.4 Dental chain in Dubai (clinics-ae), fit only but strong
- Fit 3 (10). Can-pay: 3 branches (+6), 9 dentists (+6), 610 reviews (+6), implants from AED 5,000 (+5), booking widget (+3), custom site (+2), dental_chain (+3) = 31, capped at **30**.
- Intent 0. Reach business mobile 0.85.
- `total = round(40 / 80 * 100 * 0.85) = 43` = **C**. Waits for a signal. With a fresh `review_pain` (6 points, decay 1.0, intent 6) it becomes `round(46 / 80 * 100 * 0.85) = 49`, still C. With `hiring_frontdesk` as well (8 + 6 + 2 bonus = 16): `round(56 / 80 * 100 * 0.85) = 60` = **B**.

These examples show the design intent: strong can-pay alone is not enough; a real, fresh reason to buy now is what lifts a business to A or B.

---

## 11.8 Pitch mode, angle and test group

### 11.8.1 Pitch mode (A.12.4)
```python
def pitch_mode_of(kept_signals: list[dict]) -> str:
    cats = {s["category"] for s in kept_signals}
    if "stated_need" in cats:
        return "stated_need"
    if "visible_pain" in cats:
        return "visible_pain"
    return "fit_only"
```

### 11.8.2 Angle
Angles are short codes listed per segment in YAML `angles:`, each with a one-line description the message writer receives.

| Pitch mode | Strongest signal (highest value) | Angle code |
|---|---|---|
| stated_need | any stated_need signal | `build_what_they_asked` (the need itself is in `signals.details.need`) |
| visible_pain | `hiring_frontdesk` | `frontdesk_load` |
| visible_pain | `review_pain` | `missed_calls` |
| visible_pain | `ads_running` (with or without `no_booking`) | `ad_leads_cold` |
| visible_pain | `no_booking` | `no_online_booking` |
| visible_pain | `slow_site` | `slow_site` |
| fit_only | none | segment default, for example clinics `after_hours_enquiries`, real estate `site_visit_followup`, education `admission_followup` |

Growth signals (`new_place`, `new_branch`, `news`) add intent but never choose the angle alone. When a growth signal is the strongest, the angle is the segment's growth angle (for example `new_branch_setup`).

### 11.8.3 Test group
`test_group = f"{segment_id}:{pitch_mode}:{angle}"` (A.12.4).

**Fit-only cap:** across one morning run, per segment, leads with `pitch_mode = 'fit_only'` may be at most 10% of all new leads created that day (rounded up, minimum 1). Extra fit-only businesses keep their score but are not turned into leads; their `businesses.status` stays `researched` with `reject_reason = null` and `scores.reasons.capped = 'fit_only_cap'`. They are eligible again tomorrow.

---

## 11.9 Persisting scores

1. Insert a new `scores` row per business per run (keep history; never update old rows).
2. Fields: `version = SCORE_VERSION`, `fit`, `can_pay`, `intent`, `reach`, `total`, `grade`, `pitch_mode`, `reasons`, `computed_at`.
3. Status: grade A or B means `businesses.status = 'qualified'`. C stays `researched`. D means `dormant`, re-researched no sooner than 90 days after `researched_at`.
4. Re-scoring is cheap (no AI), so `nlead score --all` re-scores every researched business after a version bump.

---

## 11.10 Judge: the top model reviews the best half

### 11.10.1 Who gets judged
Among businesses scored in this run with `fit >= 2`, sort by `total` and take the top 50% (and always every A). Skip businesses whose facts and signals have not changed since their last judgement (compare a hash of fact ids, signal ids and score total). This keeps the expensive model on the work that matters.

### 11.10.2 Input to `judge_lead` (Gemini 3.1 Pro on the Balanced tier)
- Segment, country, city, packaged outcome name (A.2.2).
- The rule score with its reasons (11.6).
- Verified facts as a list of `{id, field, value, quote, url}`.
- Active signals as `{id, type, category, observed_at, quote, url}`.
- Contacts summary (type only, never the full number).
- Allowed angles for the segment.

### 11.10.3 Output schema (enforced by the router)
```python
from typing import Literal
from pydantic import BaseModel, Field

class LeadJudgement(BaseModel):
    judge_grade: Literal["A", "B", "C", "D"]
    cited_ids: list[str] = Field(min_length=1, description="fact or signal ids supporting the grade")
    judge_note: str = Field(max_length=280, description="at most 2 plain sentences, why this lead is worth contacting now")
    best_angle: str
    risks: list[str] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1)
```

### 11.10.4 Guardrails enforced in code
1. **At most one grade step:** if the rule grade is B, the judge can only return A, B or C. Anything else is clamped to the nearest allowed grade.
2. **Citations must exist:** every id in `cited_ids` must belong to this business's verified facts or active signals. If any id is unknown, the judgement is discarded (rule grade stands) and the run stats count `judge_bad_citation`.
3. **No new facts:** every number and every capitalised name in `judge_note` must appear in the cited facts or signals (simple token check). Otherwise the note is replaced by a rule-built note.
4. **Two sentences max, plain words, no dashes:** count sentence ends; strip dashes; if it fails, use the rule-built note.
5. `best_angle` must be one of the segment's angles, else keep the rule angle.
6. The final grade is `judge_grade` after clamping. Store `judge_grade`, `judge_note`, `judge_model` on the same `scores` row, and set `scores.grade` to the final grade.

### 11.10.5 Rule-built note (fallback)
When the judge is skipped or its note is rejected, build one from the reasons, for example: "Hiring a front desk executive on Apna 5 days ago, and 420 Google reviews across 2 branches." The app shows this text under **"Why this lead"**.

### 11.10.6 Prompt (stored in `engine/prompts/judge_lead.md`)
Key instructions inside the prompt:
- "You are reviewing a lead for Nument, a small AI-first software studio. Decide whether this business is likely to buy a solution worth ₹50,000 or more in the next 30 days."
- "Use ONLY the facts and signals given. Cite their ids. Do not add any fact that is not listed."
- "You may move the grade by at most one step from the rule grade."
- "Write `judge_note` as at most two short, plain sentences a busy founder can read in five seconds."
- "If the business looks like an agency, a big chain or a hospital, say so in `risks`."

## 11.11 Creating and updating leads

After the final grade is known:

| Final grade | Existing lead for the business | Action |
|---|---|---|
| A or B | none, or only closed leads past their cool-down | **Create** a lead: `stage = 'new'`, `grade`, `score_id`, `pitch_mode`, `test_group`, `angle`, `segment_id`, `created_at = now()`. Queue it for Step 12 |
| A or B | open lead with `stage = 'new'` | **Update** `grade`, `score_id`, `pitch_mode`, `test_group`, `angle`. If the angle or the cited facts changed, clear `message` so Step 12 rewrites it |
| A or B | open lead with any stage beyond `new` (contacted, talking and so on) | **Do not touch the lead.** Only the new `scores` row is stored for history |
| C or D | open lead with `stage = 'new'` | Leave it, but lower `grade` so it sinks in the list. If D for 2 runs in a row, set `stage = 'not_a_fit'` with an `activities` row `source = 'engine'` |
| any | closed lead in cool-down (`not_now`: 30 days, `lost`: 90 days, `not_a_fit`: 180 days, `wrong_contact`: until a new verified contact exists) | Do nothing |

Rules:
- Only one open lead per business (unique partial index in Step 2).
- Every engine change to a lead writes an `activities` row with `source = 'engine'`, `type = 'grade_change'` or `'lead_created'`, and the old and new values in `payload`.
- The engine never changes a lead's `stage` except the D-twice rule above, and never edits `notes`, `deal_value_inr` or the touch dates.

## 11.12 Done when
- [ ] Unit tests reproduce the four worked examples in 11.7 exactly (same totals and grades).
- [ ] Decay tests: a signal at 29%, 31%, 59%, 61%, 99% and 101% of its window gets 1.0, 0.7, 0.7, 0.4, 0.4 and 0.0.
- [ ] Stacking tests: one type gives no bonus, two types give +2, three or more give +4; two signals with the same `event_key` count once.
- [ ] Every `scores` row has `version`, readable `reasons` with fact or signal ids, and a `pitch_mode`.
- [ ] Fit-only leads never exceed 10% of a day's new leads per segment.
- [ ] The judge never moves a grade by more than one step, and a fake citation in a mocked response discards the judgement.
- [ ] "Why this lead" shows a judge note or a rule-built note for every A and B lead.
- [ ] A lead at stage `contacted` keeps all its fields after a re-score.
- [ ] `nlead score --all --env dev` re-scores 1,000 businesses in under 2 minutes (no AI).

> **Names this step needs that are not yet in A.12:** `engine/config/scoring.yaml` (default weights); segment YAML keys `fit`, `can_pay`, `ticket_class`, `angles`, `scoring` (Step 3 should define them); fact fields `branches_count`, `staff_count`, `price_point`, `decision_maker`, `in_house_tech`, `is_agency`, `services`, `booking_method`, `contact_form_url` (Step 9.7 should define them); `signals.details.event_key`, `signals.details.need`, `signals.details.apply_by` (Step 7 should set them).

---

---

# Step 12: Message writing

**Goal:** for every new or changed lead, write a first WhatsApp message in the founder's approved voice, plus an alternate, two follow-up drafts and (when there is no mobile) an email version. Every specific claim must come from a verified fact or signal. Then lint it, check it with a second model, and store it.

**Needs first:** Step 11 (leads with `pitch_mode`, `angle`, `test_group`), Step 10 (`v_verified_facts`, contacts), Step 4 (tasks `write_message`, `check_message`).

**Runs in:** morning run, after judge: `nlead message`.

**File:** `engine/src/nument_engine/pipeline/message.py`, prompts `engine/prompts/write_message.md` and `engine/prompts/check_message.md`.

---

## 12.1 Inputs for each lead

| Input | Source | Example |
|---|---|---|
| Greeting name | Decision maker contact, else none | "Dr. Rao", "Dhruv", or no name ("Hi,") |
| Business name | `businesses.name`, short form (strip "Pvt Ltd", "LLP", "Private Limited") | "Calmveda" |
| Where we saw them | The strongest signal's `source` mapped to a plain label | "your post on Apna", "your careers page", "your Google listing", "a news piece" |
| What we saw | The signal's `quote` and `details` | "hiring two front desk executives for the Baner branch" |
| One idea | Pitch mode + angle + the packaged outcome for the domain (A.2.2) | "an AI front desk that answers every WhatsApp enquiry within seconds and books the slot" |
| Facts allowed | `v_verified_facts` rows with ids, plus active signals with ids | ids the writer must cite |
| Voice rules | A.2.3 and `lead-engine/data/whatsapp_playbook.md` voice v2 | casual, one idea, one question |
| Country notes | Segment country | India or UAE (12.8) |

Never pass the phone number or email to the writer. It does not need them.

## 12.2 Greeting rules
| Who | Greeting |
|---|---|
| Doctor with a confirmed surname | "Hi Dr. Surname," |
| Founder or owner with a confirmed first name | "Hi Firstname," |
| Name not confirmed by a verified fact | "Hi," (never guess a name) |
| Name only from a search snippet | Treat as not confirmed |

Never use "Dear Sir/Madam", "Respected", "Greetings of the day" or a surname alone.

## 12.3 How each pitch mode is written

### 12.3.1 `stated_need`: agency pitch on exactly what they asked
1. Opener: where we saw the need, in plain words.
2. One honest line about Nument ("We're Nument, a small dev team, and we build this kind of thing.").
3. One concrete idea for **their** request: what we would build first and what changes for them.
4. One short question that is easy to answer.

### 12.3.2 `visible_pain`: packaged outcome for the domain
1. Opener: the pain we noticed, said kindly (never "your reviews are bad"; say "noticed a few reviews mention calls going unanswered").
2. One honest line about Nument.
3. The packaged outcome from A.2.2, in plain words and tied to their situation ("an AI front desk that answers every WhatsApp enquiry within seconds, even at 11 pm, and books the slot").
4. One short question.

### 12.3.3 `fit_only`: the gentlest version
1. Opener: something specific and true about them (branches, a new service, their area).
2. One honest line about Nument.
3. The segment's default angle, framed as a question of interest.
4. One short question.

## 12.4 What `write_message` returns

Model on the Balanced tier: GPT-5 mini as the first choice (Step 4 maps the task).

### 12.4.1 Provider fallback (founder requirement, 12 Nov 2026)
OpenAI is currently unavailable, so `write_message` must keep working without it. It uses the AI router's **fallback chain** from Step 4, never a hard-coded provider:

| Order | Writer model for `write_message` | When it is used |
|---|---|---|
| 1 | GPT-5 mini (OpenAI) | OpenAI key present and the API answers |
| 2 | Gemini 3 Flash (verify the exact model id at build) | OpenAI missing, out of quota, erroring after retries, or disabled in `settings` |

`engine/config/tasks.yaml` declares it like this (shape only; Step 4 owns the file):

```yaml
write_message:
  tier: balanced
  chain:
    - {provider: openai, model: gpt-5-mini}
    - {provider: gemini, model: gemini-3-flash}   # verify id at build
  schema: MessageDraft
```

The router tries each entry in order, records which one answered, and logs the cost under the model that actually ran. `leads.message_model` stores that model, for example `gemini-3-flash / write_message@v3`, so the weekly report (Step 16) can compare reply rates by writer.

**Quality is judged the same way whichever provider wrote the message.** Lint (12.5), the claim check (12.6), the variety check (12.7), the 10-point critic with its pass mark of 9 (12.9) and the golden-set evaluation (Step 17) apply unchanged. A fallback message that scores under 9 is flagged for the founder exactly like any other.

Output schema:

```python
from pydantic import BaseModel, Field

class Claim(BaseModel):
    text: str = Field(description="the specific claim as it appears in the message")
    ids: list[str] = Field(min_length=1, description="fact or signal ids that prove it")

class MessageDraft(BaseModel):
    message: str
    message_alt: str = Field(description="same lead, a different opener or angle")
    followup_d3: str = Field(description="adds one new useful thing, never 'just bumping this'")
    followup_d7: str = Field(description="polite close, for example 'Shall I close this for now?'")
    email_subject: str | None = None
    email_body: str | None = None
    claims: list[Claim]
```

Rules for each field:

| Field | Words | Must |
|---|---|---|
| `message` | 30 to 60 | Start with the greeting, say where we saw them, name Nument once, one idea, exactly one question mark |
| `message_alt` | 30 to 60 | A different opener or angle, same rules |
| `followup_d3` | 15 to 45 | One new thing (a short example, a scope idea), one question |
| `followup_d7` | 10 to 30 | A polite close with one question, for example "Shall I close this for now?" |
| `email_subject` | 3 to 8 | Only when there is no mobile. Plain, no clickbait, for example "Front desk enquiries at Calmveda" |
| `email_body` | 50 to 110 | Only when there is no mobile. Same voice, may sign off as Aditya from Nument |

## 12.5 Lint (code, no AI)

Ported from `lead-engine/scripts/wa_to_edits.py`, extended.

```python
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F1E6-\U0001F1FF]")
PRICE = re.compile(r"₹|\brs\.?\s*\d|\binr\b|\baed\b|\$\s*\d|\blakh\b|\bcrore\b|\bper month\b|/month|\bk\b\s*(?:per|/)", re.I)
LINK = re.compile(r"https?://|www\.|\.com\b|\.in\b|\.ae\b|\.io\b", re.I)
DASH = re.compile("[\u2013\u2014]| - ")
BANNED = (
    "businesses like yours", "ai-powered", "ai powered", "hope you are", "hope you're", "hope this finds",
    "reaching out", "synergy", "leverage", "cutting-edge", "cutting edge", "game-changer", "game changer",
    "revolutioni", "quick 10-minute call", "just following up", "just bumping", "greetings of the day",
    "dear sir", "dear madam", "respected", "kindly", "revert", "we are a leading", "state-of-the-art",
    "world-class", "one-stop", "guaranteed results",
)

def lint(text: str, kind: str = "message") -> list[str]:
    words = len(text.split())
    lo, hi = {"message": (30, 60), "message_alt": (30, 60), "followup_d3": (15, 45), "followup_d7": (10, 30)}[kind]
    problems = []
    if not lo <= words <= hi:
        problems.append(f"{words} words (want {lo} to {hi})")
    if kind in ("message", "message_alt"):
        if not text.startswith(("Hi ", "Hi,")):
            problems.append("must start with 'Hi'")
        if "Nument" not in text:
            problems.append("does not name Nument")
    if text.count("?") != 1:
        problems.append(f"{text.count('?')} question marks (want exactly 1)")
    if LINK.search(text):
        problems.append("contains a link")
    if DASH.search(text):
        problems.append("contains a dash")
    if EMOJI.search(text):
        problems.append("contains an emoji")
    if PRICE.search(text):
        problems.append("mentions a price")
    problems += [f"banned phrase '{b}'" for b in BANNED if b in text.lower()]
    return problems
```

Hyphenated words that are normal English ("follow up", "front desk") are fine; the dash rule only catches en and em dashes and a spaced hyphen used as a dash.

## 12.6 Claim check (code, no AI)

1. Every `Claim.ids` entry must be the id of a verified fact or active signal **of this business**. Unknown id: fail.
2. Every number in `message` and `message_alt` (digits, written numbers such as "two", "five") must appear in the value or quote of at least one cited fact or signal.
3. Every capitalised word sequence that is not the greeting name, "Nument", a weekday, a month or a city of the segment must appear in a cited fact or signal (catches invented product or place names).
4. A claim that fails sends the message back to the writer once with the list of failures. Second failure: keep the best version and flag it (12.9).

## 12.7 Daily variety check

1. Compare each new `message` with all messages created today in the same segment using `rapidfuzz.fuzz.token_set_ratio` on normalised text. Above 85 with any of them: regenerate once with the instruction "use a different opener and a different question".
2. Track the first four words of every message created today. No opener pattern may be used by more than 30% of the day's messages in a segment.
3. Track the closing question. No exact question may appear in more than 25% of the day's messages.

These checks keep a batch of 100 messages from reading like a template.

## 12.8 Country and language notes

### 12.8.1 India
- English by default, simple words. No Hinglish unless the founder enables it per segment later.
- "Dr." for doctors. First names for founders.
- Never mention prices or rupees in the first message.

### 12.8.2 UAE
- English by default. Many owners are from South Asia, Europe or the Arab world; plain, polite English works for all.
- Greet by first name ("Hi Ahmed,") or "Hi Dr. Surname,". No honorifics beyond "Dr.".
- The UAE weekend is Saturday and Sunday. The send list in the app marks Friday afternoons as low priority (prayer time) and shows UAE leads in UAE time.
- Name the emirate or area when it is in a verified fact ("your Jumeirah clinic").
- Do not mention AED, prices or "cheap". Do not mention India in a way that suggests a low-cost vendor; "a small dev team" is enough.
- Phone links use the `971` country code.

## 12.9 Second-model check: `check_message`

**The critic must be a different model from the writer whenever possible**, so a model never grades its own work.

| Writer that actually answered | Critic model (`check_message`) |
|---|---|
| GPT-5 mini (OpenAI) | Gemini 3 Flash |
| Gemini 3 Flash (fallback) | Gemini 3.1 Pro (verify id at build). About ₹1 per check, still inside the daily cap |
| If no different model is available | The same model with a fresh "strict reviewer" prompt, and the lead always gets the "Needs your edit" badge so the founder reviews it |

The router picks the critic with `exclude_model = <writer model>` (Step 4 supports this option on the chain).

Rubric (10 points), same as the WhatsApp playbook:

| Criterion | Points |
|---|---|
| Personal, specific detail from their own post, page or listing | 2 |
| Relevance of the one idea to their situation | 2 |
| Easy to reply to in 5 seconds | 2 |
| Length and clarity | 1 |
| Tone: sounds like a person texting, not a brochure or a bot | 1 |
| Every fact true according to the facts provided | 2 |

Output schema:

```python
class MessageCheck(BaseModel):
    score: int = Field(ge=0, le=10)
    issues: list[str] = Field(default_factory=list, max_length=5)
    suggested_fix: str | None = None
```

Flow:
1. Check `message`. If `score >= 9`: done.
2. If `score < 9`: one rewrite with `write_message`, passing the critic's `issues` as feedback. Lint, claim check and variety check again, then `check_message` again.
3. Still under 9: keep the higher-scoring version, set `leads.message_check_score` to its score, and write an `activities` row `source = 'engine'`, `type = 'message_flagged'` with the issues. The app shows a **"Needs your edit"** badge on the lead.
4. Store `leads.message_model` (for example `gpt-5-mini` with the prompt version, `write_message@v3`).

## 12.10 WhatsApp links

Links are **built when shown** (in the app and sheet), never stored, so a phone fix updates them instantly.

| Where | Link |
|---|---|
| Desktop (WhatsApp Web) | `https://web.whatsapp.com/send?phone={digits}&text={urlencoded message}` |
| Phone (WhatsApp app) | `https://wa.me/{digits}?text={urlencoded message}` |

- `{digits}` is the E.164 number without the plus sign, for example `919876543210` (India) or `971501234567` (UAE).
- Only for contacts with `phone_type = 'mobile'`, not `do_not_contact`, and not in `suppression`.
- Landline only: show "Call" with the number and the email or form link instead.
- URL-encode with `urllib.parse.quote(message, safe="")` in Python and `encodeURIComponent` in the web app. Line breaks become `%0A`.

```python
from urllib.parse import quote

def wa_links(e164: str, message: str) -> dict[str, str]:
    digits = e164.lstrip("+")
    text = quote(message, safe="")
    return {"web": f"https://web.whatsapp.com/send?phone={digits}&text={text}",
            "app": f"https://wa.me/{digits}?text={text}"}
```

## 12.11 Storing the result
| Column | Value |
|---|---|
| `leads.message` | The final first message |
| `leads.message_alt` | The alternate |
| `leads.followup_d3`, `leads.followup_d7` | The two follow-up drafts |
| `leads.message_model` | Model and prompt version |
| `leads.message_check_score` | 0 to 10 from the critic |
| Email subject and body (no mobile) | See the note at the end of this step |

A message is rewritten only when: the lead is still `new` **and** (the message is empty, the angle changed, the cited facts changed, or the founder pressed "Regenerate" in the app). A message the founder edited by hand is never overwritten; the app writes an `activities` row `type = 'message_edited'`, and Step 12 skips leads with that activity.

## 12.12 Worked examples

All examples are illustrations of voice and structure. In real runs every detail must come from verified facts.

### 12.12.1 Clinics, `stated_need`
> Hi Dr. Mehta, came across your post on Apna for a developer to build an appointment app for your skin clinics.
>
> We're Nument, a small dev team, and we build this kind of thing. Honestly I'd start with WhatsApp booking first, since that's where most patients already message you.
>
> Is the app still on your list?

### 12.12.2 Clinics, `visible_pain` (front desk hiring)
> Hi Dr. Rao, saw you're hiring two front desk executives for the Baner branch.
>
> We're Nument, a small dev team. We set up an AI front desk on WhatsApp that answers enquiries in seconds and books the slot, so your new staff only handle the tricky calls.
>
> Worth a look?

### 12.12.3 Clinics, `visible_pain` (review pain)
> Hi, noticed a few Google reviews for Glow Skin Studio mention calls not getting picked up in the evenings.
>
> We're Nument, a small dev team. We build an AI front desk that replies on WhatsApp within seconds, even at 11 pm, and books the appointment.
>
> Would that help the front desk?

### 12.12.4 Real estate, `stated_need`
> Hi Karan, came across your post looking for someone to set up a CRM and follow ups for your property leads.
>
> We're Nument, a small dev team, and we build exactly this. I'd start by having every portal lead answered on WhatsApp in seconds and pushed into the CRM.
>
> Still looking for someone on this?

### 12.12.5 Real estate, `visible_pain` (telecaller hiring)
> Hi Neha, saw Skyline Realty is hiring telecallers for the Dwarka Expressway projects.
>
> We're Nument, a small dev team. We build an AI lead qualifier that answers every enquiry within seconds, asks budget and timeline, and books the site visit for your team.
>
> Has the hiring worked out?

### 12.12.6 Education, `visible_pain` (counsellor hiring)
> Hi Ritu, saw your post for admissions counsellors at the Indiranagar centre.
>
> We're Nument, a small dev team. We build an AI admissions counsellor on WhatsApp that answers fee and batch questions instantly and books the demo class.
>
> Is admission season keeping the team busy?

### 12.12.7 Education, `stated_need`
> Hi Arjun, came across your job post for a web developer to rebuild the GlobalEdge website and student portal.
>
> We're Nument, a small dev team, and we build this kind of thing. I'd start with the enquiry form going straight to WhatsApp so no student lead sits waiting.
>
> Has someone picked this up yet?

### 12.12.8 UAE clinic, `visible_pain`
> Hi Dr. Khan, saw you're hiring a receptionist for the Jumeirah clinic.
>
> We're Nument, a small dev team. We set up an AI front desk on WhatsApp that answers patients in seconds, day or night, and books the slot so your receptionist handles the rest.
>
> Would that take some load off?

### 12.12.9 Follow-up examples
- Day 3: "Hi Dr. Rao, one quick idea: the same setup can also remind patients a day before, which usually cuts no-shows. Want me to send a 60-sec video of it?"
- Day 7: "Hi Dr. Rao, I don't want to crowd your inbox. Shall I close this for now?"

### 12.12.10 Bad examples and why they fail
| Bad message | Why it fails |
|---|---|
| "Dear Sir, Greetings of the day! We are a leading AI-powered software company offering cutting-edge solutions for businesses like yours." | Formal, banned phrases, says nothing about them |
| "Hi, I'm reaching out from Nument. Your internship post mentions Pabbly, n8n, WhatsApp, email, TagMango and Razorpay." | Repeats their post as a list (reads like a bot), "reaching out" |
| "Hi Karan, we can build your CRM for ₹1.5 lakh with 30 days free support. Interested? Shall we talk tomorrow?" | Price in the first message, two questions, pushy |
| "Hi Dr. Mehta, check out our work at nument.in" | Link in the first message, no idea, no question about them |
| "Hi Neha, saw your 40 projects in Gurugram..." (the site says 12) | Invented number: fails the claim check |
| "Hi Ritu 🙂 quick question..." | Emoji, vague |

## 12.13 Pitfalls
- **Do not let the writer see raw page text.** Give it facts with ids. Raw text invites invented details.
- **Do not reuse yesterday's message for a new lead in the same company group.** The variety check only covers today, so seed it with the last 7 days for the same `web_domain`.
- **Do not send the alternate by mistake.** The app's main "Open WhatsApp" button always uses `message`; the alternate needs a deliberate "Use alternate" click.
- **Watch the word count after the founder edits.** The app runs the same lint in the browser and warns, but never blocks a founder's edit.

## 12.14 Done when
- [ ] `nlead message --env dev --limit 30` writes `message`, `message_alt`, `followup_d3`, `followup_d7` for 30 leads, and an email subject and body for leads without a mobile.
- [ ] 100% of stored messages pass lint; failures are flagged, not stored silently.
- [ ] The claim check rejects a mocked message that invents a number or a name.
- [ ] No opener pattern is used by more than 30% of a day's messages per segment, and no closing question by more than 25%.
- [ ] Messages scoring under 9 after one rewrite show the "Needs your edit" badge in the app.
- [ ] Web and app WhatsApp links open with the exact message text for an Indian and a UAE test number.
- [ ] A founder-edited message is never overwritten by the next run.
- [ ] With `OPENAI_API_KEY` removed, `nlead message --env dev --limit 10` still writes all messages through Gemini 3 Flash, `leads.message_model` names the Gemini model, and the critic is Gemini 3.1 Pro (never the writer's model).
- [ ] Fallback messages pass the same lint, claim check, variety check and critic threshold as OpenAI messages.
- [ ] The founder reads 20 random dev messages and rates at least 18 as "would send as is".

> **Names this step needs that are not yet in A.12:** `leads.channel` (`whatsapp`, `email`, `form`), `leads.email_subject`, `leads.email_body`; activity types `message_flagged`, `message_edited`, `lead_created`, `grade_change`; router support in Step 4 for a per-task fallback `chain` in `tasks.yaml` and an `exclude_model` option (so the critic is never the writer's model). Add the columns in Step 2 and list the activity types in Step 15's timeline.

---

# Step 13: Google Sheet two-way sync

## 13.1 Goal

Keep the two Google Sheets (master `Leads-main` and caller `Leads-Associate`) as **editable views** of the database. The founder can work from the web app or from the sheet, and both stay in sync:

- **Push:** database to sheet. Rebuilds the three tabs (Today, Pipeline, Lead details) in the approved design.
- **Pull:** sheet to database. Reads the cells people are allowed to edit and writes real edits into the database, with an activity log.
- **Sync:** pull, then push. This is what the scheduler runs.

The database is always the source of truth. The sheet never decides what a lead *is*; it only carries edits that people made.

## 13.2 What we port from the old engine

The old file `~/Desktop/lead-engine/scripts/sync_sheet.py` (about 1,000 lines) already has a design the founder approved on 16 Oct 2026 and several hard lessons. Port these pieces; do not redesign them.

| Old piece (in `sync_sheet.py`) | New home | Notes |
|---|---|---|
| Fonts, colours, `f()`, `txt()`, `num()`, `formula()`, `rich()`, `rule()`, `side()`, `HAIRLINE`, `INSET` | `sheet/design.py` | Same look: Figtree body, Newsreader display, DM Mono labels |
| `STAGES`, `STAGE_STYLE`, `canon_stage()` | `sheet/design.py` | Keyed by the DB stage value (A.12.2) with a display label |
| `GRADE_STYLE`, `NOTES` (header notes) | `sheet/design.py` | Same wording, minus anything about the old engine |
| `pipeline_columns()`, `build_pipeline()` | `sheet/push.py` | Columns now come from the database view `v_sheet_leads` |
| `build_today()`, `tasks_today()`, `due_on()` | `sheet/push.py` + `sheet/design.py` | Today list sized at push time |
| `build_details()`, `text_height()` | `sheet/push.py` | Row height fits the longest cell |
| `wa_link()` | `sheet/design.py` | WhatsApp Web link (desktop) |
| `editable_values()`, `read_back_reviews()`, `written_values()`, snapshot logic (D-045) | `sheet/pull.py` | Snapshots now live in the `sheet_snapshots` table, not JSON files |
| `ensure_tabs()`, `reset()`, `grid()`, `row_heights()`, `put()`, `merge()`, `borders()`, `protect()` | `sheet/push.py` | Same behaviour |

### 13.2.1 Lessons that must survive the port
1. **A crashed push must never be read back as edits.** On 12 Nov 2026 a push crashed after the tabs were reset, and the next read-back saw blank cells and undid 13 stage changes. The new design adds a `sheet_state` marker (13.7.4) and only reads sheets marked `ok`.
2. **Build everything first, write last.** All requests for all tabs are built in memory and validated before any reset happens.
3. **Unknown stages never crash.** A stage typed by hand that is not in A.12.2 is kept as typed, shown in grey, and logged. It never raises.
4. **Snapshots are written only after a full successful write.** A partial write leaves the old snapshot in place.
5. **Each sheet compares against its own snapshot.** A stale caller sheet can never undo an edit made on the master sheet, and the other way round.
6. **No money on the caller sheet.** Asserted in code before writing.

## 13.3 Sheets, tabs and columns

### 13.3.1 Master vs caller
| | Master (`SHEET_MASTER_ID`) | Caller (`SHEET_CALLER_ID`) |
|---|---|---|
| Who uses it | Founder | Associate (Aditya) |
| Money columns | Deal value, ₹ total on the Won tile, Their budget, Ticket basis | None. Asserted in code |
| "Who" column labels | You / Associate | Founder / You |
| Editable cells | Stage, WA, Call, Day 3, Day 7, Meeting, Deal value, Notes | Stage, WA, Call, Day 3, Day 7, Meeting, Notes |
| Conflict priority between sheets | Wins over caller | Loses to master |

In `APP_ENV=dev` both views are written into the staging spreadsheet `SHEET_STAGING_ID`: the master view in tabs `Today`, `Pipeline`, `Lead details`, and the caller view in tabs `Today (caller)`, `Pipeline (caller)`, `Lead details (caller)`.

### 13.3.2 Which leads appear
A lead appears on both sheets when **either** is true:
- grade is `A` or `B` and the stage is not closed, or
- the stage is anything other than `new` (once someone has worked on a lead it never disappears mid-conversation).

Add this view in a new migration (`0005_sheet_views.sql`) if Step 2 did not create it:

```sql
create or replace view v_sheet_leads as
select
  l.id                 as lead_id,
  l.grade, l.stage, l.pitch_mode, l.test_group, l.angle,
  l.message, l.message_alt, l.followup_d3, l.followup_d7,
  l.wa_at, l.call_at, l.d3_at, l.d7_at, l.meeting_at,
  l.next_step, l.due_at, l.deal_value_inr, l.notes,
  l.updated_at         as lead_updated_at,
  b.id                 as business_id,
  b.name, b.city, b.country, b.website, b.segment_id,
  s.total              as score_total, s.judge_note, s.reasons,
  c.name               as contact_name, c.role as contact_role,
  c.phone_e164, c.phone_type, c.email, c.source as phone_source,
  sig.type             as top_signal_type, sig.quote as top_signal_quote,
  sig.url              as top_signal_url, sig.observed_at as top_signal_at
from leads l
join businesses b on b.id = l.business_id
left join scores s on s.id = l.score_id
left join lateral (
  select * from contacts c
  where c.business_id = b.id and not c.do_not_contact
  order by c.is_decision_maker desc, (c.phone_type = 'mobile') desc, c.verified desc
  limit 1
) c on true
left join lateral (
  select * from signals g
  where g.business_id = b.id and (g.expires_at is null or g.expires_at > now())
  order by g.points desc, g.observed_at desc
  limit 1
) sig on true
where (l.grade in ('A','B') and l.stage not in
        ('won','retainer','lost','not_now','not_a_fit','wrong_contact'))
   or l.stage <> 'new';
```

### 13.3.3 Row order
- Rows keep the order they had in the last snapshot, so a person working down the sheet is not confused.
- New leads are appended at the end, best first (score total, then grade, then signal freshness).
- `nlead sheet push --resort` re-ranks every row. Use it only on request.

### 13.3.4 Pipeline columns
| Key | Header | Width | Source (from `v_sheet_leads`) | Editable | Master only |
|---|---|---|---|---|---|
| `grade` | Grade | 52 | `grade` | no | no |
| `company` | Company | 176 | `name` (shortened to 24 chars) | no | no |
| `person` | Person | 156 | `contact_name` | no | no |
| `phone` | Phone · WhatsApp | 222 | `phone_e164` + WhatsApp link | no | no |
| `why` | Why now | 262 | `top_signal_quote` shortened, or `judge_note` | no | no |
| `stage` | Stage | 140 | `stage` (display label) | **yes** | no |
| `wa` | WA | 78 | `wa_at` | **yes** | no |
| `call` | Call | 78 | `call_at` | **yes** | no |
| `d3` | Day 3 | 78 | `d3_at` | **yes** | no |
| `d7` | Day 7 | 78 | `d7_at` | **yes** | no |
| `meeting` | Meeting | 84 | `meeting_at` | **yes** | no |
| `next` | Next step | 158 | live formula (13.6.3) | no | no |
| `due` | Due | 100 | live formula | no | no |
| `bar` | Win chance | 128 | `score_total` as a text bar | no | no |
| `deal` | Deal value | 112 | `deal_value_inr` | **yes** | **yes** |
| `notes` | Notes | 240 | `notes` | **yes** | no |
| hidden: `dd` | Due date | 80 | live formula | no | no |
| hidden: `queue` | Queue | 50 | live formula | no | no |
| hidden: `who` | Who | 80 | live formula | no | no |
| hidden: `wa_url` | WA link | 80 | WhatsApp Web URL | no | no |
| hidden: `label` | Phone label | 80 | phone or "Email ↗" | no | no |
| hidden: `group` | Test group | 80 | `test_group` | no | no |
| hidden: `id` | ID | 60 | `lead_id` (uuid) | no | no |

### 13.3.5 Editable field map (pull)
| Sheet header | DB column | Parse rule |
|---|---|---|
| Stage | `leads.stage` | `canon_stage()`: match the display label case-insensitively, return the snake-case value. Unknown text is kept as typed in `activities.payload` and the stage is left unchanged |
| WA, Call, Day 3, Day 7, Meeting | `wa_at`, `call_at`, `d3_at`, `d7_at`, `meeting_at` | Read with `valueRenderOption=UNFORMATTED_VALUE`, `dateTimeRenderOption=SERIAL_NUMBER`. Serial number to date (epoch 1899-12-30). Text dates parsed with `dateutil`. Blank means cleared |
| Deal value (master) | `deal_value_inr` | Digits, commas and dots only are a number. Text such as "₹1.2L" is converted (`L` = 100,000, `K` = 1,000, `Cr` = 10,000,000). The grey estimate text written by push is ignored (see 13.8.3) |
| Notes | `notes` | Trimmed string |

## 13.4 Module layout

```
engine/src/nument_engine/sheet/
├── __init__.py
├── client.py      # gspread + Drive client from GOOGLE_SERVICE_ACCOUNT_JSON or _FILE
├── design.py      # styles, stage map, cell builders, formulas, links, next-step logic
├── push.py        # DB -> sheet (build in memory, validate, write, snapshot)
└── pull.py        # sheet -> DB (read, diff against snapshot, resolve, apply)
```

### 13.4.1 `sheet/client.py`
```python
"""Google API clients for the sheet sync. The service account needs edit access on all three spreadsheets."""
import json
from functools import lru_cache

import gspread
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from ..settings import get_settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",  # file modifiedTime for conflict timestamps
]


@lru_cache
def credentials() -> Credentials:
    s = get_settings()
    if s.google_service_account_json:                      # CI: full JSON in a secret
        info = json.loads(s.google_service_account_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(s.google_service_account_file, scopes=SCOPES)


@lru_cache
def gc() -> gspread.Client:
    return gspread.authorize(credentials())


def drive_modified_time(spreadsheet_id: str) -> str:
    """ISO time the spreadsheet file was last modified (any cell, any user). Used as the sheet-edit timestamp."""
    sess = AuthorizedSession(credentials())
    r = sess.get(f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}",
                 params={"fields": "modifiedTime", "supportsAllDrives": "true"}, timeout=30)
    r.raise_for_status()
    return r.json()["modifiedTime"]
```

Setup once per spreadsheet: share it with the service account email (Editor). The old service account `~/.config/lead-engine/service-account.json` already has access to both real sheets. Share the staging spreadsheet with it too.

## 13.5 `sheet/design.py`

### 13.5.1 Constants (ported)
```python
FONT, DISPLAY, MONO = "Figtree", "Newsreader", "DM Mono"
INK, TX2, SUB, FAINT, MUTED = "1F1F1F", "3D3D3D", "666666", "999999", "BDBDBD"
INDIGO, IND300, IND200, HEAD_BG, HAIR = "3333CC", "A7C0F1", "D2DFF9", "FCFCFC", "F0F0F0"
WA_GREEN, LINK = "1FA855", "3333CC"

# DB value -> (display label, background, text). Order = dropdown order.
STAGES: dict[str, tuple[str, str, str]] = {
    "new":              ("New",              "F2F2F2", "525252"),
    "contacted":        ("Contacted",        "E8EFFC", "212191"),
    "talking":          ("Talking",          "D2DFF9", "11115B"),
    "discovery_booked": ("Discovery booked", "FCEAF0", "9D2055"),
    "discovery_done":   ("Discovery done",   "F9D5E1", "871F4B"),
    "proposal_sent":    ("Proposal sent",    "FFF0CF", "8A5A00"),
    "won":              ("Won",              "E3F1D8", "385418"),
    "retainer":         ("Retainer",         "D9F0EA", "0F5C52"),
    "lost":             ("Lost",             "FDE7E2", "A21913"),
    "not_now":          ("Not now",          "FEEDE6", "A5460F"),
    "not_a_fit":        ("Not a fit",        "F5F5F5", "999999"),
    "wrong_contact":    ("Wrong contact",    "F3EEE8", "7A5536"),
}
CLOSED = {"won", "retainer", "lost", "not_now", "not_a_fit", "wrong_contact"}
LABEL_TO_STAGE = {label.lower(): key for key, (label, _, _) in STAGES.items()}
UNKNOWN_STAGE_STYLE = ("FFFFFF", "999999")
GRADE_STYLE = {"A": ("496D21", "E3F1D8"), "B": ("3333CC", "E8EFFC"), "C": ("666666", "F5F5F5"), "D": ("999999", "FAFAFA")}


def canon_stage(text: str | None) -> tuple[str | None, str]:
    """Return (db_value or None if unknown, original text). Never raises."""
    t = (text or "").strip()
    if not t:
        return "new", t
    return LABEL_TO_STAGE.get(t.lower()) or (t if t in STAGES else None), t


def stage_label(value: str) -> str:
    return STAGES.get(value, (value, "", ""))[0]
```

### 13.5.2 Cell builders
Copy `rgb()`, `f()`, `side()`, `txt()`, `fmt_only()`, `num()`, `formula()`, `rich()`, `rule()`, `col()`, `serial()`, `from_serial()`, `links_cell()` from the old file unchanged. They only build JSON for the Sheets `batchUpdate` API, so they need no database access.

### 13.5.3 WhatsApp link
```python
import urllib.parse

def wa_web_link(phone_e164: str | None, phone_type: str | None, message: str) -> str:
    """Desktop link: opens WhatsApp Web straight to the chat with the message typed (founder's choice, 12 Nov 2026).
    Only for mobiles. Landlines get no WhatsApp link."""
    if not phone_e164 or phone_type != "mobile":
        return ""
    digits = phone_e164.lstrip("+")
    return f"https://web.whatsapp.com/send?phone={digits}&text={urllib.parse.quote(message)}"
```
The web app (Step 15) also offers the `https://wa.me/{digits}?text=...` app link for phones. The sheet keeps the desktop link because the founder sends from a computer.

### 13.5.4 Next step and due date (Python twin of the sheet formula)
The sheet shows live formulas so that typing a date updates "Next step" and "Due" immediately. The database keeps `leads.next_step` and `leads.due_at` for the web app. Both must use the same rules, so the Python twin lives here and is unit-tested against the formula on a fixture.

```python
import datetime as dt

def next_step_and_due(lead: dict, today: dt.date, queue_pos: int | None, new_per_day: int) -> tuple[str, dt.date | None]:
    s = lead["stage"]
    wa, call, d3, d7, mt = (lead.get(k) for k in ("wa_at", "call_at", "d3_at", "d7_at", "meeting_at"))
    touches = [d for d in (wa, call, d3, d7) if d]
    last = max(touches) if touches else None
    day = dt.timedelta(days=1)
    if s in ("won",):                  return "Kick-off", None
    if s == "retainer":                return "Monthly review", None
    if s == "wrong_contact":           return "Find the right number", None
    if s in ("lost", "not_a_fit"):     return "", None
    if s == "not_now":                 return "Check back", (last or today) + 30 * day
    if s == "proposal_sent":           return "Follow up proposal", (mt + 4 * day) if mt else today
    if s == "discovery_done":          return "Send proposal", (mt + 2 * day) if mt else today
    if s == "discovery_booked":        return "Discovery call", mt or today
    if s == "talking":                 return "Book discovery call", (last + day) if last else today
    if s == "contacted" and not wa:    return "Call", today
    if not wa:                         return "Send WhatsApp", today if (queue_pos and queue_pos <= new_per_day) else None
    if not call:                       return "Call", wa + day
    if not d3:                         return "Day 3 follow-up", wa + 3 * day
    if not d7:                         return "Last touch", wa + 7 * day
    return "Move to Not now", d7 + day
```
`new_per_day` is the settings key `send_per_day` (default 50): how many brand-new leads appear in Today each day. The founder can raise it any time from the app.

### 13.5.5 Header notes
Port `NOTES` from the old file. Update two texts:
- "Grade": "A = start here, B = next. C and D stay in the database and come back when they show a new signal."
- "Why now": "Their freshest buying signal. The proof link is in Lead details and in the app."

## 13.6 `sheet/push.py` (database to sheet)

### 13.6.1 Algorithm
```
push(target, conn, dry_run, resort):
  1. LOCK      pg_try_advisory_lock(hashtext('nument-sheet-' || target.name)); if not acquired: exit 0 (another sync is running)
  2. READ      rows = select * from v_sheet_leads; order rows (13.3.3)
  3. BUILD     reqs_pipeline, snap = build_pipeline(rows, target)        # in memory only
               reqs_today         = build_today(rows, target, tab_ids)
               reqs_details       = build_details(rows, target)
  4. VALIDATE  assert_no_money(target, all_headers, all_rows)            # caller only
               assert every row has a lead id; assert len(snap) == len(rows)
               assert total request payload < 9 MB (Sheets limit 10 MB per batchUpdate)
  5. DRY RUN?  print counts and the first 5 rows; return
  6. MARK      settings.sheet_state[target.name] = {"state": "writing", "run_id": ..., "at": now}
  7. WRITE     ensure_tabs -> for each tab: reset(tab) + batch_update(reqs_tab)
  8. SNAPSHOT  one transaction: delete from sheet_snapshots where sheet = target.name;
               insert all snap rows (values exactly as pull will read them); written_at = now
  9. MARK      settings.sheet_state[target.name] = {"state": "ok", "run_id": ..., "at": now}
 10. UNLOCK
```
If anything fails between steps 6 and 9, the state stays `writing`. The next pull skips that sheet and the next push rebuilds it fully. No edits can be lost and no blank cells can be read as edits.

### 13.6.2 Snapshot values must match what pull reads
`snapshot_values(row, target)` returns exactly what `pull.read_editable()` will return for an untouched row:
```python
def snapshot_values(row: dict, target: "Target") -> dict:
    vals = {
        "stage": row["stage"],
        "notes": (row["notes"] or "").strip(),
        **{k: (row[k].isoformat() if row[k] else "") for k in ("wa_at", "call_at", "d3_at", "d7_at", "meeting_at")},
    }
    if target.money:
        dv = row["deal_value_inr"]
        vals["deal_value_inr"] = "" if dv is None else str(int(dv)) if float(dv).is_integer() else str(dv)
    return vals
```
Dates in `leads` are stored as `date` in IST. Never store a time for these five columns.

### 13.6.3 Live formulas on the Pipeline tab
Port the old `IFS` formulas for Next step, Due date (hidden), Due (visible), Queue (hidden) and Who (hidden), using the stage display labels. Keep these rules from the old file:
- "Contacted" without a WA date means the first WhatsApp went out; the next step is "Call", due today.
- "Retainer" gives "Monthly review" with no due date. "Wrong contact" gives "Find the right number" with no due date.
- "Queue" counts New leads with no WA date above this row; only the first `send_per_day` are due today.
- The "Who" column shows "You" for founder steps (Discovery call, Send proposal, Follow up proposal, Kick-off, Monthly review) on master and "Founder" on caller.

### 13.6.4 Today tab sizing
- Count the tasks due today with `next_step_and_due()` over all rows (same rules as the formulas).
- `cap = min(settings.today_rows_max (default 60), max(1, tasks_due_today))`.
- The Today list uses a single spill formula (`LET`, `FILTER`, `SORT`, `ARRAY_CONSTRAIN` to `cap` rows) exactly like the old design, plus a "+N more due today · open Pipeline ↗" link (`HYPERLINK("#gid=...")`) when more than `cap` tasks are due.
- KPI tiles stay as in the old design: Contacted this week (target from settings `weekly_contact_target`, default 150), Conversations, Discovery calls, Proposals sent, Won (₹ total on master only), Overdue.

### 13.6.5 Lead details tab
Columns: Grade, Company, Person and role, Why now (signal with date and proof link), WhatsApp message (with "Open in WhatsApp ↗" link), Alternate message, Day 3 follow-up, Day 7 follow-up, Score note (judge note and top reasons), Proof links, Email, Watch-outs, Checked on. Master adds: Can-pay notes (from `scores.reasons`). Row heights use the ported `text_height()` with a 64 px minimum.

### 13.6.6 Caller money assertion
```python
MONEY_PATTERN = re.compile(r"ticket|budget|deal|₹|price|value", re.I)

def assert_no_money(target: "Target", headers: list[str], rows: list[list[dict]]) -> None:
    if target.money:
        return
    bad = [h for h in headers if MONEY_PATTERN.search(h)]
    if bad:
        raise AssertionError(f"money columns on the caller sheet: {bad}")
    for r in rows:
        for cell in r:
            v = (cell.get("userEnteredValue") or {}).get("stringValue", "")
            if "₹" in v:
                raise AssertionError("a ₹ amount reached the caller sheet")
```
"Win chance" is allowed (it is a score, not money). Message texts never contain prices (Step 12 lint), so they pass.

## 13.7 `sheet/pull.py` (sheet to database)

### 13.7.1 Algorithm
```
pull(conn, dry_run):
  1. LOCK same advisory lock as push for each target
  2. For target in (master, caller):
       if settings.sheet_state[target] != "ok": log "skipped, last push incomplete"; continue
       sheet_vals[target] = read_editable(target)            # {lead_id: {field: value}}
       snap[target]       = load_snapshot(target)            # from sheet_snapshots
       sheet_time[target] = drive_modified_time(target.id)   # upper bound of any edit time
  3. db_vals = current editable values of the leads seen (one query)
     db_change_time = latest activities.at per (lead, field) where source = 'app' and at > snapshot written_at
  4. For each lead and editable field: resolve (13.7.3) -> list of Change(lead, field, old, new, source, winner_reason)
  5. Apply in one transaction:
       update leads set <field> = new, updated_at = now(), last_activity_at = now()
       insert activities (source='sheet', type='edit' or 'stage_change', payload={field, from, to, sheet})
       side effects (13.7.5)
  6. Recompute next_step and due_at for every changed lead (design.next_step_and_due)
  7. Return stats {read, changed, conflicts, unknown_stages, skipped_sheets}
```

### 13.7.2 Reading the editable cells
```python
def read_editable(target) -> dict[str, dict[str, str]]:
    ws = gc().open_by_key(target.spreadsheet_id).worksheet(target.tab("Pipeline"))
    res = ws.spreadsheet.values_get(f"'{ws.title}'", params={
        "valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"})
    rows = res.get("values", [])
    hrow = next(i for i, r in enumerate(rows[:6]) if "ID" in r and "Stage" in r)   # header row (row 2 in the design)
    idx = {h: i for i, h in enumerate(rows[hrow])}
    out = {}
    for r in rows[hrow + 1:]:
        cell = lambda h: r[idx[h]] if h in idx and idx[h] < len(r) else ""
        lead_id = str(cell("ID")).strip()
        if len(lead_id) != 36:                     # uuid; skip blank and footer rows
            continue
        stage_db, raw = canon_stage(str(cell("Stage")))
        vals = {"stage": stage_db or f"?{raw}", "notes": str(cell("Notes") or "").strip()}
        for key, header in (("wa_at", "WA"), ("call_at", "Call"), ("d3_at", "Day 3"),
                            ("d7_at", "Day 7"), ("meeting_at", "Meeting")):
            vals[key] = parse_date_cell(cell(header))   # "" or "YYYY-MM-DD"
        if target.money:
            vals["deal_value_inr"] = parse_money_cell(cell("Deal value"), lead_id)
        out[lead_id] = vals
    return out
```
A stage value starting with `?` is an unknown stage: it is logged (activity type `unknown_stage`, payload `{text}`) and the DB stage is not changed. The next push writes the DB stage back, so the cell corrects itself.

### 13.7.3 Conflict rules
For one lead and one field, with `S` = snapshot value, `M` = master sheet value, `C` = caller sheet value, `D` = current DB value:

| Case | Condition | Result |
|---|---|---|
| 1. Nothing changed | `M == S`, `C == S` (or sheet skipped) | No change |
| 2. Sheet edit only | One sheet differs from its snapshot, `D == S` | Apply the sheet value. Activity `edit` (source sheet) |
| 3. App edit only | Sheets equal snapshot, `D != S` | Nothing to do here; the push will write `D` to the sheet |
| 4. Same edit both sides | Sheet value equals `D` | No change (already in sync) |
| 5. Sheet vs app conflict | A sheet differs from its snapshot **and** `D != S` **and** sheet value `!= D` | **Most recent wins.** Sheet time = Drive `modifiedTime` of that spreadsheet. App time = latest `activities.at` for that field with source `app`. The loser is logged as activity `conflict_overridden` with both values and both times |
| 6. Master vs caller conflict | Both sheets changed the field to different values | Master wins (rule from the old engine). Caller value logged as `conflict_overridden` |
| 7. Unknown stage text | Sheet stage is not in A.12.2 | DB unchanged, activity `unknown_stage`, next push restores the cell |
| 8. Lead missing in DB | ID in sheet not in `leads` | Ignore and log (row will disappear on the next push) |

Each sheet is compared only to **its own** snapshot. This is the D-045 rule that fixed the 12 Nov 2026 bug.

### 13.7.4 The `sheet_state` marker
Settings key `sheet_state` holds `{"master": {"state": "ok", "run_id": "...", "at": "..."}, "caller": {...}}`. Push sets `writing` before resetting any tab and `ok` after the snapshot is saved. Pull only reads sheets whose state is `ok`.

If a sheet is stuck in `writing` (a crash), the health check (Step 22) shows it, and the next push rebuilds that sheet fully without reading it. Edits typed into a half-built sheet during that window are lost. This window lasts at most one run (seconds to a few minutes), and the health page shows the warning.

### 13.7.5 Side effects of certain edits
| Edit | Side effect |
|---|---|
| Stage moves from `new` to anything else and `wa_at` is empty | Set nothing automatically. The formula treats "Contacted without WA date" as sent today; the DB copies the rule so the app shows the same next step |
| Stage becomes `wrong_contact` | `contacts.do_not_contact = true` for the phone on that lead, insert `suppression(phone_e164, reason='wrong_contact')` |
| Stage becomes `won` or `retainer` | Activity `won`; the learning loop (Step 16) counts it |
| `deal_value_inr` set on a non-won lead | Allowed (a quoted value) |
| Any edit | `leads.updated_at` and `last_activity_at` set to now |

### 13.7.6 Money parsing
```python
def parse_money_cell(v, lead_id: str) -> str:
    """Return a whole-rupee string or ''. Grey estimates written by push (ranges such as '₹3L to 8L') are not edits."""
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else str(v)
    s = str(v).strip().replace(",", "")
    if " to " in s:                                   # estimate range written by push, never an edit
        return ""
    m = re.fullmatch(r"₹?\s*([\d.]+)\s*(cr|l|lakh|k)?", s, re.I)
    if not m:
        return ""                                     # unreadable text: ignore, logged by caller
    n = float(m.group(1)) * {"cr": 1e7, "l": 1e5, "lakh": 1e5, "k": 1e3}.get((m.group(2) or "").lower(), 1)
    return str(int(round(n)))
```

## 13.8 Sync command and frequency

### 13.8.1 `nlead sheet sync`
1. `pull` (both sheets).
2. `push` master.
3. `push` caller.
4. Record a `runs` row (kind `sheet_sync`) with stats.

`nlead sheet sync --light` (used by the daytime schedule) skips the Lead details tab rebuild when no lead was added or removed since the last full push. It only rewrites Today and Pipeline. This keeps each daytime run near 1 minute.

### 13.8.2 When it runs
| When (IST) | Trigger | Mode |
|---|---|---|
| About 06:20 | End of the morning run (Step 14) | Full push (new leads added) |
| 09:00, 11:00, 13:00, 15:00, 17:00, 19:00, 21:00 | `sheet-sync.yml` | `--light` |
| Any time | `workflow_dispatch` or the app's "Sync sheet now" button (Step 15) | Full |

App edits appear in the sheet at the next sync (within 2 hours in the day). Sheet edits appear in the app at the next sync. The app shows "Sheet last synced at" so nobody is surprised.

### 13.8.3 Estimates in the Deal value column
On master, an empty `deal_value_inr` shows a grey estimate range from `scores.reasons.ticket_estimate` (for example "₹1L to 3L"). Pull ignores any value containing " to " (13.7.6), so estimates are never read back as edits. The snapshot stores `""` for these rows.

## 13.9 Dry runs and staging
- `nlead sheet push --env dev --dry-run`: builds everything, validates, prints row counts and the first rows. Writes nothing.
- `nlead sheet sync --env dev`: real write to `SHEET_STAGING_ID` (both views, 13.3.1).
- Before go-live (Step 21), run the round-trip test below on staging twice.

### 13.9.1 Round-trip test (staging)
1. Push. Note 3 lead IDs.
2. In the staging sheet: set lead 1 Stage to "Talking", lead 2 WA to today, lead 3 Notes to "test note".
3. In the app (dev): change lead 3 Notes to "app note" **after** step 2.
4. Run `nlead sheet sync --env dev`.
5. Expect: lead 1 talking, lead 2 wa_at today, lead 3 notes "app note" (app edit was later), and one `conflict_overridden` activity for lead 3.
6. Type "Maybe later" into lead 1 Stage. Sync. Expect: stage unchanged, an `unknown_stage` activity, and the cell shows "Talking" again.
7. Kill a push midway (Ctrl+C after "WRITE" starts). Confirm `sheet_state` is `writing`, run `pull`, and confirm it skips the sheet and changes nothing. Run `push`, confirm the state is `ok`.

## 13.10 Pitfalls
- **Header renames break pull.** Pull finds columns by header text. If you rename a header, update both `pipeline_columns()` and `read_editable()` in the same commit, and add a test.
- **Date cells with times.** If someone types "12 Nov 3pm", the serial has a fraction. `parse_date_cell` keeps only the date.
- **Sorting the sheet by hand.** Allowed. Pull matches by the hidden ID column, not by row number.
- **Deleting a row in the sheet.** The lead is not deleted in the DB; it comes back on the next push. Deleting is done in the app (stage "Not a fit").
- **Sheets API limits.** 300 read requests per minute per project and 60 per minute per user. Push uses one batch per tab; pull uses one read per sheet. Never call per row.
- **Protected ranges are warning-only**, as in the old design. People can override the warning; pull ignores any non-editable column anyway.

## 13.11 Tests
| Test | What it proves |
|---|---|
| `test_canon_stage` | Every label in A.12.2 maps both ways; unknown text returns `None` and never raises |
| `test_snapshot_roundtrip` | `snapshot_values(row)` equals `read_editable()` on a cell grid built by `build_pipeline(row)` |
| `test_conflict_cases` | All 8 cases of 13.7.3 with fixed timestamps |
| `test_stale_sheet_cannot_undo` | The 12 Nov 2026 bug: caller stale, master edited, nothing undone |
| `test_writing_state_skipped` | A sheet in `writing` state is never read |
| `test_no_money_caller` | Building the caller view with a deal value present raises |
| `test_next_step_twin` | Python `next_step_and_due` matches a table of expected formula results |
| `test_money_parse` | "₹1.2L" is 120000; "₹3L to 8L" is ""; "abc" is "" |

## 13.12 Done when
- [ ] `sheet/design.py`, `sheet/push.py`, `sheet/pull.py`, `sheet/client.py` exist and pass the tests in 13.11.
- [ ] `v_sheet_leads` exists in the database.
- [ ] `nlead sheet push --env dev --dry-run` prints row counts with no writes.
- [ ] The staging round-trip test (13.9.1) passes twice, including the crash test.
- [ ] The caller view contains no money column and no ₹ amount (asserted in code and checked by eye).
- [ ] Today shows exactly the tasks due today, capped by `today_rows_max`, with a "+N more" link when needed.
- [ ] WhatsApp links open WhatsApp Web with the message typed.
- [ ] `sheet_state` is `ok` for both sheets after a normal run.

---

---

# Step 14: Orchestration with GitHub Actions

## 14.1 Goal
Run the engine on a schedule in the cloud, with no laptop involved, inside the free 2,000 minutes a month of GitHub Actions for private repositories:
- **Night run** (02:00 IST): collect, filter, crawl, submit the AI batch.
- **Morning run** (06:00 IST): collect the AI batch, verify, score, judge, write messages, full sheet push.
- **Sheet sync** (every 2 hours, 09:00 to 21:00 IST): light two-way sync.
- **Weekly** (Monday 07:00 IST): learning, report, audit.
- **Monthly** (22:30 IST on the 1st): universe refresh.
- **Backup** (Sunday 23:00 IST): encrypted database dump.

## 14.2 Secrets and environments

### 14.2.1 GitHub environments
Create two environments in the repository settings (Settings, Environments): `dev` and `prod`. Put each secret in both environments with the right value for that environment. Scheduled runs use `prod`. Manual runs choose.

### 14.2.2 Secrets (per environment)
| Secret | Value |
|---|---|
| `DATABASE_URL` | Supabase **session pooler** URI (port 5432, IPv4). Not the direct connection: GitHub runners have no IPv6 |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (engine only) |
| `GEMINI_API_KEY` | Google AI Studio key, paid tier |
| `OPENAI_API_KEY` | OpenAI key with a monthly usage limit set in the OpenAI dashboard |
| `GOOGLE_MAPS_API_KEY` | Restricted to Places API (New) and PageSpeed Insights API |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The full JSON of the service account key (multi-line is fine) |
| `BACKUP_PASSPHRASE` | Long random passphrase (store a copy in the founder's password manager) |

### 14.2.3 Variables (per environment, not secret)
`SHEET_MASTER_ID`, `SHEET_CALLER_ID`, `SHEET_STAGING_ID`, `ASSOCIATE_NAME` (`Aditya`), `USER_AGENT` (`NumentLeadBot/1.0 (+https://nument.in)`), `ALERT_EMAIL` (optional).

Command line alternative (needs the `gh` CLI, logged in as the founder):
```bash
gh secret set DATABASE_URL --env prod --body "$DATABASE_URL"
gh variable set ASSOCIATE_NAME --env prod --body "Aditya"
```
Never paste secret values into chat, issues, commit messages or logs.

## 14.3 Shared setup action

Create `.github/actions/setup-engine/action.yml`. Every workflow uses it, so the setup is defined once.

```yaml
name: Setup engine
description: Install uv, Python 3.12, engine dependencies, optional Chromium, and the service account file
inputs:
  playwright:
    description: Install Chromium for Playwright (night run only)
    required: false
    default: "false"
runs:
  using: composite
  steps:
    - name: Install uv (with cache)
      uses: astral-sh/setup-uv@v6        # pin to a full commit SHA on the build day
      with:
        enable-cache: true
        cache-dependency-glob: engine/uv.lock

    - name: Install Python 3.12
      shell: bash
      run: uv python install 3.12

    - name: Install engine dependencies
      shell: bash
      working-directory: engine
      run: uv sync --frozen --no-dev

    - name: Cache Playwright browsers
      if: inputs.playwright == 'true'
      uses: actions/cache@v4             # pin to a full commit SHA on the build day
      with:
        path: ~/.cache/ms-playwright
        key: playwright-${{ runner.os }}-${{ hashFiles('engine/uv.lock') }}

    - name: Install Chromium and its system libraries
      if: inputs.playwright == 'true'
      shell: bash
      working-directory: engine
      run: uv run playwright install --with-deps chromium

    - name: Write service account file
      shell: bash
      run: |
        if [ -n "${GOOGLE_SERVICE_ACCOUNT_JSON:-}" ]; then
          printf '%s' "$GOOGLE_SERVICE_ACCOUNT_JSON" > "$RUNNER_TEMP/sa.json"
          chmod 600 "$RUNNER_TEMP/sa.json"
          echo "GOOGLE_SERVICE_ACCOUNT_FILE=$RUNNER_TEMP/sa.json" >> "$GITHUB_ENV"
        fi
```
Composite actions cannot read `secrets` directly. Each job sets the secrets as `env`, and the action reads them from the environment.

## 14.4 `pipeline/runs.py`: the orchestration

### 14.4.1 Design
- A run is a list of **phases**. Each phase is a function that reads pending work from the database, does it, and returns stats.
- Before each phase, the budget guard (Step 19) decides whether the phase may run, based on its **priority** and today's spend.
- **Essential** phases (health, prefilter, verify, score, sheet sync) cost nothing or almost nothing and always run. If an essential phase fails, the run is `failed` and stops.
- **Non-essential** phases that fail are recorded, the run continues, and the final status is `partial`.
- Every phase is **idempotent**: it only picks work that is still pending (for example businesses with status `queued` and no pages fetched today). Re-running a crashed run simply continues.
- One run of each kind at a time: a Postgres advisory lock per kind. GitHub `concurrency` groups add a second guard.

### 14.4.2 Phase table
| Run | Order | Phase | Calls | Essential | Budget priority |
|---|---|---|---|---|---|
| night | 1 | `health` | `ops.health.check_all(fail_fast=True)` | yes | n/a |
| night | 2 | `universe_incremental` | `pipeline.universe.incremental()` | no | 2 |
| night | 3 | `signals` | `pipeline.signals.run_all()` | no | 3 (uses grounded search) |
| night | 4 | `prefilter` | `pipeline.prefilter.build_queue()` | yes | n/a |
| night | 5 | `research` | `pipeline.research.crawl_queue()` (fit_only items last) | no | 1 for fit_only, 2 for low priority, 4 otherwise |
| night | 6 | `extract_submit` | `pipeline.extract.submit()` (Gemini batch) | no | 4 |
| morning | 1 | `health` | `ops.health.check_all()` | yes | n/a |
| morning | 2 | `extract_collect` | `pipeline.extract.collect(max_wait_min=10)` | no | n/a (already paid) |
| morning | 3 | `verify` | `pipeline.verify.run()` | yes | n/a |
| morning | 4 | `score` | `pipeline.score.run()` | yes | n/a |
| morning | 5 | `judge` | `pipeline.judge.run()` (top half) | no | 4 |
| morning | 6 | `message` | `pipeline.message.run()` | no | 5 |
| morning | 7 | `sheet_sync` | `sheet.pull` + full `sheet.push` | yes | n/a |
| morning | 8 | `report` | `ops.health.daily_summary()` | yes | n/a |
| sheet | 1 | `catch_up` (09:00 run only) | collect late batch items, then verify, score, judge, message only those | no | as above |
| sheet | 2 | `sheet_sync` | `sheet.sync(light=True)` | yes | n/a |
| weekly | 1 | `learn` | `learn.reweight.run()` | no | n/a |
| weekly | 2 | `report` | `learn.report.weekly()` | yes | n/a |
| weekly | 3 | `audit` | `ops.audit.weekly()` (Pro on 20 leads) | no | 4 |
| monthly | 1 | `universe_full` | `pipeline.universe.refresh(monthly=True)` | no | 2 |
| monthly | 2 | `prune` | delete raw `pages.text` older than 90 days for rejected or dormant businesses | yes | n/a |

### 14.4.3 Skeleton
```python
"""Orchestrated runs used by GitHub Actions: `nlead run night|morning|sheet|weekly|monthly`."""
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import traceback
from typing import Callable

from ..budget import BudgetGuard, BudgetStop
from ..db import connect, advisory_lock
from ..logging import get_logger

log = get_logger(__name__)


@dc.dataclass
class Phase:
    name: str
    fn: Callable[..., dict]
    essential: bool = False
    priority: int | None = None          # None = free / not budget-gated


def night_phases(): ...                  # returns the list from 14.4.2
def morning_phases(): ...


def run(kind: str, *, env: str, segments: list[str] | None, limit: int | None, dry_run: bool) -> int:
    with connect(env) as conn, advisory_lock(conn, f"nument-run-{kind}") as got:
        if not got:
            log.warning("run already in progress", kind=kind)
            return 0
        run_id = conn.execute(
            "insert into runs(kind, started_at, status, stats) values (%s, now(), 'running', '{}') returning id",
            (kind,)).fetchone()[0]
        guard = BudgetGuard(conn, run_id)
        stats, status = {}, "ok"
        for ph in PHASES[kind]():
            if ph.priority is not None and not guard.allow_phase(ph.priority):
                stats[ph.name] = {"skipped": "budget"}
                status = "partial"
                continue
            t0 = dt.datetime.now()
            try:
                stats[ph.name] = ph.fn(conn=conn, run_id=run_id, segments=segments,
                                       limit=limit, dry_run=dry_run, guard=guard) or {}
                stats[ph.name]["seconds"] = round((dt.datetime.now() - t0).total_seconds(), 1)
            except BudgetStop as e:                       # cap reached mid-phase
                stats[ph.name] = {"stopped": "budget", "detail": str(e)}
                status = "partial"
            except Exception as e:                        # noqa: BLE001
                stats[ph.name] = {"error": repr(e), "trace": traceback.format_exc()[-2000:]}
                if ph.essential:
                    status = "failed"
                    break
                status = "partial"
            conn.execute("update runs set stats = %s where id = %s", (stats, run_id))   # progress visible in the app
        conn.execute("update runs set finished_at = now(), status = %s, stats = %s where id = %s",
                     (status, stats, run_id))
        return 1 if status == "failed" else 0             # non-zero only for real failures
```
Rules:
- Each phase function accepts `conn, run_id, segments, limit, dry_run, guard` and returns a small stats dict.
- `--dry-run` means: no batch submission, no sheet writes, no paid search calls; collection and crawling still run with `--limit` (default 5 in dry runs).
- Progress is written to `runs.stats` after every phase, so the app's Health page (Step 15) shows a live run.

### 14.4.4 Batch timing between night and morning
- Night submits the Gemini batch at about 02:30 IST. Gemini batches usually finish within minutes to a few hours (the published target is 24 hours).
- Morning polls for up to 10 minutes. Items still pending stay pending.
- The 09:00 IST sheet-sync run has a `catch_up` phase: it collects any finished items and processes only those (verify, score, judge, message). If nothing finished, it costs seconds.
- Items pending for more than 26 hours are resubmitted once (synchronously) the next morning, then marked failed.

## 14.5 Workflow files

All cron times are UTC. IST is UTC+5:30. GitHub may start scheduled runs a few minutes late at busy times; every workflow tolerates that.

### 14.5.1 `.github/workflows/night.yml`
```yaml
name: Night run
on:
  schedule:
    - cron: "30 20 * * *"            # 02:00 IST
  workflow_dispatch:
    inputs:
      env:
        description: Environment
        type: choice
        options: [prod, dev]
        default: prod
      segment:
        description: Segment id (empty = all enabled)
        required: false
        default: ""
      limit:
        description: Max businesses to research (empty = settings value)
        required: false
        default: ""
      dry_run:
        description: Dry run (no batch submit, no paid search, no sheet writes)
        type: boolean
        default: false

permissions:
  contents: read

concurrency:
  group: nument-pipeline-${{ inputs.env || 'prod' }}
  cancel-in-progress: false

jobs:
  night:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    environment: ${{ inputs.env || 'prod' }}
    env:
      APP_ENV: ${{ inputs.env || 'prod' }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      GOOGLE_MAPS_API_KEY: ${{ secrets.GOOGLE_MAPS_API_KEY }}
      GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
      SHEET_MASTER_ID: ${{ vars.SHEET_MASTER_ID }}
      SHEET_CALLER_ID: ${{ vars.SHEET_CALLER_ID }}
      SHEET_STAGING_ID: ${{ vars.SHEET_STAGING_ID }}
      ASSOCIATE_NAME: ${{ vars.ASSOCIATE_NAME }}
      USER_AGENT: ${{ vars.USER_AGENT }}
      IN_SEGMENT: ${{ inputs.segment }}
      IN_LIMIT: ${{ inputs.limit }}
      IN_DRY_RUN: ${{ inputs.dry_run }}
    steps:
      - uses: actions/checkout@v4          # pin to a full commit SHA on the build day
      - uses: ./.github/actions/setup-engine
        with:
          playwright: "true"

      - name: Night run
        working-directory: engine
        run: |
          ARGS=(--env "$APP_ENV")
          [ -n "$IN_SEGMENT" ] && ARGS+=(--segment "$IN_SEGMENT")
          [ -n "$IN_LIMIT" ] && ARGS+=(--limit "$IN_LIMIT")
          [ "$IN_DRY_RUN" = "true" ] && ARGS+=(--dry-run)
          uv run nlead run night "${ARGS[@]}"

      - name: Run summary
        if: always()
        working-directory: engine
        run: uv run nlead health --summary --env "$APP_ENV" >> "$GITHUB_STEP_SUMMARY" || true
```
Inputs reach the script only through `env` (`IN_SEGMENT`, `IN_LIMIT`, `IN_DRY_RUN`), never pasted into the script with `${{ }}`. This avoids script injection.

### 14.5.2 `.github/workflows/morning.yml`
```yaml
name: Morning run
on:
  schedule:
    - cron: "30 0 * * *"             # 06:00 IST
  workflow_dispatch:
    inputs:
      env:
        type: choice
        options: [prod, dev]
        default: prod
      segment:
        required: false
        default: ""
      dry_run:
        type: boolean
        default: false

permissions:
  contents: read

concurrency:
  group: nument-pipeline-${{ inputs.env || 'prod' }}
  cancel-in-progress: false

jobs:
  morning:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: ${{ inputs.env || 'prod' }}
    env:
      APP_ENV: ${{ inputs.env || 'prod' }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      GOOGLE_MAPS_API_KEY: ${{ secrets.GOOGLE_MAPS_API_KEY }}
      GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
      SHEET_MASTER_ID: ${{ vars.SHEET_MASTER_ID }}
      SHEET_CALLER_ID: ${{ vars.SHEET_CALLER_ID }}
      SHEET_STAGING_ID: ${{ vars.SHEET_STAGING_ID }}
      ASSOCIATE_NAME: ${{ vars.ASSOCIATE_NAME }}
      USER_AGENT: ${{ vars.USER_AGENT }}
      IN_SEGMENT: ${{ inputs.segment }}
      IN_DRY_RUN: ${{ inputs.dry_run }}
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-engine      # no Chromium: morning never crawls
      - name: Morning run
        working-directory: engine
        run: |
          ARGS=(--env "$APP_ENV")
          [ -n "$IN_SEGMENT" ] && ARGS+=(--segment "$IN_SEGMENT")
          [ "$IN_DRY_RUN" = "true" ] && ARGS+=(--dry-run)
          uv run nlead run morning "${ARGS[@]}"
      - name: Run summary
        if: always()
        working-directory: engine
        run: uv run nlead health --summary --env "$APP_ENV" >> "$GITHUB_STEP_SUMMARY" || true
```

### 14.5.3 `.github/workflows/sheet-sync.yml`
```yaml
name: Sheet sync
on:
  schedule:
    - cron: "30 3-15/2 * * *"        # 09:00, 11:00, 13:00, 15:00, 17:00, 19:00, 21:00 IST
  workflow_dispatch:
    inputs:
      env:
        type: choice
        options: [prod, dev]
        default: prod
      full:
        description: Full push (rebuild Lead details too)
        type: boolean
        default: true

permissions:
  contents: read

concurrency:
  group: nument-sheet-${{ inputs.env || 'prod' }}
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    environment: ${{ inputs.env || 'prod' }}
    env:
      APP_ENV: ${{ inputs.env || 'prod' }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}      # catch_up phase only
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}      # catch_up phase only
      GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
      SHEET_MASTER_ID: ${{ vars.SHEET_MASTER_ID }}
      SHEET_CALLER_ID: ${{ vars.SHEET_CALLER_ID }}
      SHEET_STAGING_ID: ${{ vars.SHEET_STAGING_ID }}
      ASSOCIATE_NAME: ${{ vars.ASSOCIATE_NAME }}
      IN_FULL: ${{ inputs.full }}
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-engine
      - name: Sheet sync
        working-directory: engine
        run: |
          ARGS=(--env "$APP_ENV")
          [ "$IN_FULL" != "true" ] && ARGS+=(--light)
          uv run nlead run sheet "${ARGS[@]}"
```
The sheet-sync job and the morning job use different concurrency groups, so the sheet sync never waits for a long morning run. The advisory lock inside `push` and `pull` (13.6.1) prevents them from writing the same sheet at the same moment.

### 14.5.4 `.github/workflows/weekly.yml`
```yaml
name: Weekly learning and report
on:
  schedule:
    - cron: "30 1 * * 1"             # Monday 07:00 IST
  workflow_dispatch:
    inputs:
      env:
        type: choice
        options: [prod, dev]
        default: prod

permissions:
  contents: read

concurrency:
  group: nument-pipeline-${{ inputs.env || 'prod' }}
  cancel-in-progress: false

jobs:
  weekly:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: ${{ inputs.env || 'prod' }}
    env:
      APP_ENV: ${{ inputs.env || 'prod' }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
      ALERT_EMAIL: ${{ vars.ALERT_EMAIL }}
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-engine
      - name: Weekly run
        working-directory: engine
        run: uv run nlead run weekly --env "$APP_ENV"
      - name: Report in the job summary
        if: always()
        working-directory: engine
        run: uv run nlead report weekly --format markdown --env "$APP_ENV" >> "$GITHUB_STEP_SUMMARY" || true
```

### 14.5.5 `.github/workflows/monthly.yml`
```yaml
name: Monthly universe refresh
on:
  schedule:
    - cron: "0 17 1 * *"             # 22:30 IST on the 1st (finishes before the 02:00 night run)
  workflow_dispatch:
    inputs:
      env:
        type: choice
        options: [prod, dev]
        default: prod
      segment:
        required: false
        default: ""

permissions:
  contents: read

concurrency:
  group: nument-pipeline-${{ inputs.env || 'prod' }}
  cancel-in-progress: false

jobs:
  monthly:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    environment: ${{ inputs.env || 'prod' }}
    env:
      APP_ENV: ${{ inputs.env || 'prod' }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      GOOGLE_MAPS_API_KEY: ${{ secrets.GOOGLE_MAPS_API_KEY }}
      USER_AGENT: ${{ vars.USER_AGENT }}
      IN_SEGMENT: ${{ inputs.segment }}
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-engine
      - name: Monthly run
        working-directory: engine
        run: |
          ARGS=(--env "$APP_ENV")
          [ -n "$IN_SEGMENT" ] && ARGS+=(--segment "$IN_SEGMENT")
          uv run nlead run monthly "${ARGS[@]}"
```

### 14.5.6 `.github/workflows/backup.yml`
```yaml
name: Weekly database backup
on:
  schedule:
    - cron: "30 17 * * 0"            # Sunday 23:00 IST
  workflow_dispatch: {}

permissions:
  contents: read

jobs:
  backup:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    environment: prod
    env:
      APP_ENV: prod
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
      BACKUP_PASSPHRASE: ${{ secrets.BACKUP_PASSPHRASE }}
    steps:
      - uses: actions/checkout@v4
      - name: Install a pg_dump that matches the server version
        run: |
          sudo install -d /usr/share/postgresql-common/pgdg
          sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
          echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
          sudo apt-get update -qq && sudo apt-get install -y -qq postgresql-client-17
      - uses: ./.github/actions/setup-engine
      - name: Dump, encrypt, upload to Supabase Storage
        working-directory: engine
        run: uv run nlead backup --env prod --out "$RUNNER_TEMP/nument-db.sql.gz.gpg"
      - name: Keep a copy as a workflow artifact
        uses: actions/upload-artifact@v4
        with:
          name: nument-db-${{ github.run_id }}
          path: ${{ runner.temp }}/nument-db.sql.gz.gpg
          retention-days: 30
```
`nlead backup` runs `pg_dump --no-owner --no-privileges` through the session pooler, pipes it to gzip, encrypts it with `gpg --symmetric --cipher-algo AES256 --batch --passphrase-fd 0` (passphrase from `BACKUP_PASSPHRASE`), uploads it to the private Supabase Storage bucket `backups/` and deletes dumps older than 8 weeks. Check the server version in the Supabase dashboard (Settings, Infrastructure) and match the client version in the install step.

To restore: download, then `gpg --decrypt file.sql.gz.gpg | gunzip | psql "$DATABASE_URL"` into an **empty** database. Practise this once on the dev project (Step 21).

### 14.5.7 `ci.yml`
The CI workflow (lint, tests, eval subset on every push) is defined in Step 17. It shares the same setup action.

## 14.6 GitHub Actions minutes budget

GitHub bills each job rounded **up** to the whole minute. Setup with a warm cache takes about 40 to 60 seconds. Chromium install with a warm browser cache takes about 30 to 60 seconds (system libraries are installed every time).

| Workflow | Runs a month | Billed minutes per run (expected) | A month (expected) | A month (worst case) |
|---|---|---|---|---|
| Night | 30 | 28 | 840 | 1,050 (35 a run) |
| Morning | 30 | 14 | 420 | 540 (18 a run) |
| Sheet sync, light | 210 (7 a day) | 2 | 420 | 630 (3 a run) |
| Weekly | 4 to 5 | 10 | 50 | 75 |
| Monthly | 1 | 35 | 35 | 60 |
| Backup | 4 to 5 | 3 | 15 | 25 |
| CI (Step 17) | about 40 pushes | 4 | 160 | 240 |
| **Total** | | | **about 1,940** | **about 2,620** |

The expected total fits under 2,000 minutes a month, but only just. Watch it on the GitHub billing page (Settings, Billing, Usage) every week of the first month. If the month is trending over, apply these fixes **in this order**:

1. **Fewer sheet syncs:** every 3 hours instead of 2 (`"30 3-15/3 * * *"` = 09:00, 12:00, 15:00, 18:00, 21:00 IST). Saves about 120 minutes.
2. **Cheaper CI:** run CI only on pull requests and on pushes that touch `engine/**` or `web/**` (`paths` filter), and run the eval subset only when prompts or config change. Saves about 80 to 120 minutes.
3. **Faster night run:** raise crawl concurrency across different hosts (never per host), and skip Lighthouse in CI (use the PageSpeed API, which runs on Google's side). Saves about 150 minutes.
4. **Move the sheet sync off GitHub:**
   - **Render cron job:** billed per minute with a $1 a month minimum per cron job. The sync uses about 210 minutes a month on the smallest instance, so it lands at about $1 a month.
   - **Supabase `pg_cron` + an Edge Function:** free on the Supabase free tier, but the sync would have to be rewritten in TypeScript (Deno). Only do this if the founder asks.
5. **GitHub Team plan:** 3,000 minutes a month (check the current price per user before buying).

## 14.7 Failure handling and notifications
- **GitHub's own email:** a failed scheduled run emails the person who last edited the workflow file. The founder must be that person, or must watch the repository's Actions notifications (Settings, Notifications, Actions).
- **The `runs` table:** every run writes its status and stats. The app's Health page (Step 15) shows the last runs, any phase errors, and a red banner if the last night or morning run failed.
- **Job summary:** every run appends `nlead health --summary` to the GitHub job summary: counts per phase, spend today, budget state, source health.
- **Optional email:** if `ALERT_EMAIL` is set, `nlead health --notify` sends a short alert on `failed` runs and on the 80% budget alert (Step 19). Choose the email provider at build time (any SMTP or transactional email service with a free tier); its credentials become two more secrets.
- **Exit codes:** `nlead run` exits 1 only when an essential phase failed. A `partial` run (a skipped AI step) exits 0, so the founder is not spammed, but it shows in the Health page.

## 14.8 Manual runs
- From GitHub: Actions tab, choose the workflow, "Run workflow", fill the inputs.
- From the app (admin only, Step 15): the Engine page calls the GitHub API `POST /repos/{owner}/nument-leads/actions/workflows/{file}/dispatches` with the fine-grained token `GH_DISPATCH_TOKEN` (permission: Actions write on this repository only), server-side.
- From a laptop: `cd engine && uv run nlead run morning --env dev --dry-run`.

## 14.9 Pitfalls
- **IPv6:** GitHub-hosted runners cannot reach the Supabase direct connection. Always use the session pooler URI (port 5432) in `DATABASE_URL`.
- **Transaction pooler (port 6543) breaks advisory locks and prepared statements.** Use the session pooler.
- **Cron delay:** schedules can start several minutes late. Never schedule two dependent jobs closer than 30 minutes apart.
- **Scheduled workflows on inactive repositories:** GitHub disables schedules in public repositories after 60 days with no activity. This repository is private, but keep at least one commit a month (the Monday report can commit nothing; the monthly dependency update in Step 22 is enough).
- **Secrets in logs:** never `echo` a secret. GitHub masks registered secrets, but not values derived from them (for example a decoded JSON). The setup action writes the service account to a file and never prints it.
- **Long phases:** keep every phase under the job timeout. The research phase stops starting new businesses after 30 minutes of the night run, leaving the rest queued for the next night.

## 14.10 Done when
- [ ] Environments `dev` and `prod` exist with every secret and variable from 14.2.
- [ ] `.github/actions/setup-engine/action.yml` and the six workflow files are committed.
- [ ] `pipeline/runs.py` runs `night`, `morning`, `sheet`, `weekly` and `monthly` locally with `--env dev --dry-run` and writes a `runs` row each time.
- [ ] A manual `workflow_dispatch` of each workflow on `dev` succeeds.
- [ ] A forced failure (temporarily set a bad `GEMINI_API_KEY` in `dev`) gives a `partial` run that still pushes the sheet.
- [ ] A forced essential failure (bad `DATABASE_URL`) gives a failed run and a GitHub failure email.
- [ ] Two consecutive scheduled night + morning runs on `prod` succeed (Step 21).
- [ ] The minutes table in 14.6 is checked against the real billing page after the first full week, and the projection for the month is under 2,000.
- [ ] One backup has been restored into the dev project successfully.

---

---

# Step 15: Web app

| | |
|---|---|
| **Goal** | A private web app where the founder and the team see every lead in depth, send with one tap, change stages, edit messages, see what works, and control the engine. |
| **You need first** | Step 1 (repo skeleton with `web/`), Step 2 (Supabase dev and prod projects, migrations, RLS, views, seed with your admin user). The app does not need the engine to be live: it works on whatever rows are in the database. |
| **Founder decisions** | Next.js on **Render**. Supabase Auth **email + password, invite only**. **Nument kit** design (Newsreader, Figtree, DM Mono, indigo accents, calm, uncluttered). App and Google Sheet are **both editable**; the **database is the truth**. |
| **Time** | 2 to 3 weeks for one developer, built in parallel with the engine from week 2. |
| **Result** | `https://leads.nument.in` (or the Render URL) behind a login, with Today, Leads, Lead page, Pipeline, Insights, Engine, Inbox and Settings. |

---

## 15.1 Architecture

### 15.1.1 How the pieces talk
```
 Browser (founder, Aditya)
    |  HTTPS, session cookie (httpOnly, set by @supabase/ssr)
    v
 Next.js app on Render (Node server)
    |-- Server Components: read data with the USER session  -> Supabase (PostgREST + RLS)
    |-- Server Actions:    write data with the USER session  -> Supabase (RLS decides)
    |-- Admin actions only: service role key (server only)   -> Supabase Auth admin, Storage
    |-- Engine control:    GitHub REST API (workflow_dispatch) with GH_DISPATCH_TOKEN
    v
 Supabase Postgres  <---- engine (GitHub Actions) writes leads every night
    ^
    |---- Google Sheet two-way sync (Step 13) reads and writes the same tables
```

### 15.1.2 Rules that keep it safe and simple
1. **Server Components by default.** Pages fetch data on the server with the user's session. Client Components are used only where the user interacts (tables, kanban, editors, toasts).
2. **All writes are Server Actions.** No custom REST API for app data. The only route handlers are `/api/health`, `/auth/confirm` and `/leads/export`.
3. **Row Level Security decides who sees what.** Every read and write from a user goes through the user's own session, so RLS (Step 2) is the real guard. The app also hides things the role cannot use, but never relies on hiding alone.
4. **The service role key never reaches the browser.** It is used only in files that start with `import 'server-only'`, and only after `requireRole(['admin'])` passes.
5. **Callers never see money.** Callers read leads through the view `v_leads_caller`, which has no `deal_value_inr`. Admins read `v_leads_admin`. Money is written only by admin actions.
6. **Every change writes an activity** (`activities` row with `source = 'app'`), so the timeline, the learning loop (Step 16) and the sheet sync (Step 13) all see it.
7. **Times are stored in UTC and shown in IST** (`Asia/Kolkata`).
8. **No em dashes or en dashes in any UI copy.** Use "to" for ranges.

### 15.1.3 Environment variables (web)
| Variable | Where | Notes |
|---|---|---|
| `APP_ENV` | server | `dev` or `prod`. Shows a "DEV" badge in the top bar when `dev`. |
| `NEXT_PUBLIC_SUPABASE_URL` | browser + server | Inlined at **build** time. Set it in Render before the first build. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | browser + server | Safe in the browser because RLS protects every table. |
| `NEXT_PUBLIC_APP_URL` | browser + server | `https://leads.nument.in` in prod, `http://localhost:3000` locally. Used in password reset links. |
| `SUPABASE_URL` | server | Same value as the public URL. Used by the admin client. |
| `SUPABASE_SERVICE_ROLE_KEY` | server only | Admin actions only. Never prefix with `NEXT_PUBLIC_`. |
| `GH_DISPATCH_TOKEN` | server only | Fine-grained GitHub token: this repo only, permission "Actions: Read and write". |
| `GH_REPO` | server | `owner/nument-leads`. |
| `GH_DISPATCH_REF` | server | Branch to run workflows on, default `main`. |

Create `web/.env.local` for local work (never committed):
```bash
APP_ENV=dev
NEXT_PUBLIC_SUPABASE_URL=https://<dev-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<dev anon key>
NEXT_PUBLIC_APP_URL=http://localhost:3000
SUPABASE_URL=https://<dev-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<dev service role key>
GH_DISPATCH_TOKEN=<fine-grained token>
GH_REPO=<owner>/nument-leads
GH_DISPATCH_REF=main
```

### 15.1.4 Folder structure (every route file)
```
web/
├── package.json
├── next.config.ts
├── postcss.config.mjs
├── tsconfig.json
├── middleware.ts                 # Next 15. In Next 16+ this file is proxy.ts (see 15.2.6)
├── playwright.config.ts
├── vitest.config.ts
├── scripts/
│   ├── copy-standalone.mjs       # copies static assets into the standalone build
│   └── seed-test-users.ts        # dev only: creates test admin + caller
├── src/
│   ├── app/
│   │   ├── layout.tsx            # fonts, globals.css, Toaster
│   │   ├── globals.css           # tokens import + Tailwind + base styles
│   │   ├── (auth)/
│   │   │   ├── layout.tsx        # centred card layout, no sidebar
│   │   │   ├── login/page.tsx
│   │   │   ├── login/actions.ts
│   │   │   ├── reset-password/page.tsx
│   │   │   ├── reset-password/actions.ts
│   │   │   └── reset-password/update/page.tsx
│   │   ├── auth/confirm/route.ts # verifies the email link (password recovery)
│   │   ├── api/health/route.ts
│   │   └── (app)/
│   │       ├── layout.tsx        # shell: sidebar, top bar, session + role
│   │       ├── loading.tsx
│   │       ├── error.tsx
│   │       ├── not-found.tsx
│   │       ├── page.tsx          # Today  (/)
│   │       ├── actions.ts        # Today actions (mark sent, skip, wrong contact, undo)
│   │       ├── leads/page.tsx
│   │       ├── leads/actions.ts  # bulk actions, saved views
│   │       ├── leads/export/route.ts
│   │       ├── leads/[id]/page.tsx
│   │       ├── leads/[id]/actions.ts
│   │       ├── pipeline/page.tsx
│   │       ├── pipeline/actions.ts
│   │       ├── insights/page.tsx
│   │       ├── engine/page.tsx
│   │       ├── engine/actions.ts
│   │       ├── inbox/page.tsx
│   │       ├── inbox/actions.ts
│   │       ├── settings/page.tsx
│   │       ├── settings/actions.ts
│   │       ├── settings/users/page.tsx
│   │       ├── settings/users/actions.ts
│   │       ├── settings/suppression/page.tsx
│   │       └── settings/suppression/actions.ts
│   ├── components/
│   │   ├── ui/                   # button, badge, card, table, tabs, drawer, kpi-tile,
│   │   │                         # empty-state, input, select, textarea, toaster
│   │   ├── shell/                # sidebar, topbar, user-menu, env-badge
│   │   ├── today/                # send-list, send-row, wa-buttons, followups
│   │   ├── leads/                # leads-table, filters, bulk-bar, saved-views
│   │   ├── lead/                 # header, contact-card, why-card, signals, facts,
│   │   │                         # tech-card, message-editor, timeline, notes, deal, feedback
│   │   ├── pipeline/             # board, column, card
│   │   ├── insights/             # funnel, rates-table, cost-chart, quality-tiles
│   │   └── engine/               # segments, budget-form, sources, runs, run-buttons, custom-queries
│   ├── lib/
│   │   ├── supabase/server.ts    # user-session client for Server Components and Actions
│   │   ├── supabase/client.ts    # browser client (only for realtime, optional)
│   │   ├── supabase/admin.ts     # service role client (server only)
│   │   ├── supabase/middleware.ts# session refresh + route guard
│   │   ├── auth.ts               # getSessionUser, requireRole
│   │   ├── stages.ts             # stage constants from A.12.2
│   │   ├── grades.ts
│   │   ├── whatsapp.ts           # web + app links
│   │   ├── lint.ts               # message lint (same rules as Step 12)
│   │   ├── dates.ts              # IST formatting
│   │   ├── csv.ts
│   │   ├── github.ts             # workflow_dispatch
│   │   ├── activity.ts           # logActivity helper
│   │   ├── queries/              # today.ts, leads.ts, lead.ts, pipeline.ts, insights.ts, engine.ts
│   │   └── database.types.ts     # generated from Supabase (15.2.4)
│   └── styles/
│       └── tokens.css            # copied from the Nument design kit
└── tests/
    ├── e2e/                      # Playwright specs
    └── unit/                     # vitest specs
```

---

## 15.2 Project setup

### 15.2.1 Create the app
Run from the repository root.
```bash
$ pnpm create next-app@latest web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm
$ cd web
```
- If the generator asks about Turbopack, say yes for dev.
- Add `"packageManager": "pnpm@<version>"` to `web/package.json` (Render uses it through corepack).

### 15.2.2 Install dependencies
```bash
$ pnpm add @supabase/ssr @supabase/supabase-js server-only zod react-hook-form @hookform/resolvers \
    @tanstack/react-table @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities recharts \
    date-fns date-fns-tz lucide-react sonner @radix-ui/react-dialog @radix-ui/react-tabs \
    @radix-ui/react-select @radix-ui/react-dropdown-menu clsx tailwind-merge
$ pnpm add -D vitest @vitejs/plugin-react @testing-library/react @testing-library/jest-dom jsdom \
    @playwright/test @axe-core/playwright supabase tsx
$ pnpm exec playwright install chromium
```
Why each one:
| Package | Use |
|---|---|
| `@supabase/ssr`, `@supabase/supabase-js` | Auth with cookies, database and storage |
| `server-only` | Build fails if a server file is imported into the browser |
| `zod`, `react-hook-form` | Validate every form and every Server Action input |
| `@tanstack/react-table` | Leads table |
| `@dnd-kit/*` | Pipeline board drag and drop (mouse, touch, keyboard) |
| `recharts` | Insights charts |
| `date-fns`, `date-fns-tz` | IST dates |
| `@radix-ui/*` | Accessible dialog, tabs, select, menus without heavy styling |
| `sonner` | Toasts (with an Undo button) |
| `lucide-react` | Small, consistent icons |

### 15.2.3 `next.config.ts`
```ts
import type { NextConfig } from 'next'

const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000'

const nextConfig: NextConfig = {
  output: 'standalone',           // small Node server for Render
  poweredByHeader: false,
  experimental: {
    serverActions: {
      bodySizeLimit: '10mb',      // proposal uploads
      allowedOrigins: [new URL(appUrl).host, 'nument-leads-web.onrender.com'],
    },
  },
  async headers() {
    return [{
      source: '/(.*)',
      headers: [
        { key: 'X-Frame-Options', value: 'DENY' },
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
      ],
    }]
  },
}
export default nextConfig
```
- If your Next.js version moved `serverActions` out of `experimental`, move the block to the top level (check the version's docs).

### 15.2.4 Generate database types
Types keep queries honest when the schema changes.
```bash
$ pnpm exec supabase login                     # once, opens a browser
$ pnpm exec supabase gen types typescript --project-id <dev-ref> > src/lib/database.types.ts
```
Add a script so anyone can refresh them:
```json
"scripts": {
  "types": "supabase gen types typescript --project-id $SUPABASE_DEV_REF > src/lib/database.types.ts"
}
```
Re-run after every migration in Step 2.

### 15.2.5 Supabase clients
`src/lib/supabase/server.ts` (user session, used by Server Components and Server Actions):
```ts
import 'server-only'
import { cookies } from 'next/headers'
import { createServerClient } from '@supabase/ssr'
import type { Database } from '@/lib/database.types'

export async function createClient() {
  const cookieStore = await cookies()           // async since Next 15
  return createServerClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (list) => {
          try {
            list.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
          } catch {
            // Called from a Server Component: the middleware refreshes the session instead.
          }
        },
      },
    },
  )
}
```
`src/lib/supabase/admin.ts` (service role, admin actions only):
```ts
import 'server-only'
import { createClient as createSb } from '@supabase/supabase-js'
import type { Database } from '@/lib/database.types'

export function createAdminClient() {
  return createSb<Database>(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
}
```
`src/lib/supabase/client.ts` (browser, only needed if you turn on Realtime, 15.5.5):
```ts
import { createBrowserClient } from '@supabase/ssr'
import type { Database } from '@/lib/database.types'
export const createClient = () =>
  createBrowserClient<Database>(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!)
```

### 15.2.6 Middleware: refresh the session and protect routes
`src/lib/supabase/middleware.ts`:
```ts
import { NextResponse, type NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'

const PUBLIC = ['/login', '/reset-password', '/auth/confirm', '/api/health']

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request })
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (list) => {
          list.forEach(({ name, value }) => request.cookies.set(name, value))
          response = NextResponse.next({ request })
          list.forEach(({ name, value, options }) => response.cookies.set(name, value, options))
        },
      },
    },
  )
  // getUser() asks Supabase to validate the token. Never trust getSession() on the server.
  // If your @supabase/ssr version offers getClaims(), it is faster and also safe.
  const { data: { user } } = await supabase.auth.getUser()
  const path = request.nextUrl.pathname
  const isPublic = PUBLIC.some((p) => path === p || path.startsWith(p + '/'))

  if (!user && !isPublic) {
    const url = request.nextUrl.clone()
    url.pathname = '/login'
    url.searchParams.set('next', path)
    return NextResponse.redirect(url)
  }
  if (user && path === '/login') {
    const url = request.nextUrl.clone()
    url.pathname = '/'
    return NextResponse.redirect(url)
  }
  // Force a password change after an admin-created temporary password (15.3.4).
  if (user?.user_metadata?.must_change_password && path !== '/settings' && !isPublic) {
    const url = request.nextUrl.clone()
    url.pathname = '/settings'
    url.searchParams.set('change_password', '1')
    return NextResponse.redirect(url)
  }
  return response
}
```
`web/middleware.ts` (Next 15):
```ts
import type { NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/middleware'

export async function middleware(request: NextRequest) {
  return updateSession(request)
}
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|webp|ico)$).*)'],
}
```
- **Next 16 and later** renamed this file to `proxy.ts` with an exported function named `proxy`. Use the name your installed version expects. The body is the same.

### 15.2.7 Session helpers and role guard
`src/lib/auth.ts`:
```ts
import 'server-only'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

export type Role = 'admin' | 'caller' | 'viewer'

export async function getSessionUser() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return null
  const { data: profile } = await supabase
    .from('profiles').select('role, full_name').eq('user_id', user.id).single()
  return {
    user,
    role: (profile?.role ?? 'viewer') as Role,
    name: profile?.full_name ?? user.email ?? 'User',
  }
}

export async function requireRole(roles: Role[]) {
  const s = await getSessionUser()
  if (!s) redirect('/login')
  if (!roles.includes(s.role)) redirect('/')
  return s
}

export const canSeeMoney = (role: Role) => role === 'admin'
export const canEdit = (role: Role) => role === 'admin' || role === 'caller'
```

### 15.2.8 Health route
`src/app/api/health/route.ts`:
```ts
export const dynamic = 'force-dynamic'
export async function GET() {
  return Response.json({ ok: true, env: process.env.APP_ENV ?? 'unknown', at: new Date().toISOString() })
}
```
Keep it free of database calls so Render's health check never fails because Supabase is slow.

---

## 15.3 Authentication and roles

### 15.3.1 Supabase dashboard settings (do this in dev and prod)
1. **Authentication, Sign In / Providers, Email:** enabled.
2. **Allow new users to sign up: OFF.** Only admins create users.
3. **Confirm email: ON** (admin-created users are created already confirmed, see 15.3.4).
4. **Password requirements:** minimum length **12**, require lowercase, uppercase, digits and symbols.
5. **URL configuration:**
   - Site URL: `https://leads.nument.in` in prod, `http://localhost:3000` in dev.
   - Redirect URLs: `http://localhost:3000/**`, `https://leads.nument.in/**`, `https://nument-leads-web.onrender.com/**`.
6. **Email template, Reset password:** change the link to the SSR-friendly form:
   ```html
   <h2>Reset your Nument Leads password</h2>
   <p><a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery&next=/reset-password/update">Set a new password</a></p>
   ```
7. **SMTP:** Supabase's built-in email sender is rate limited and meant for testing. For reliable reset emails in prod, add a custom SMTP sender (for example Resend's free tier or a Gmail app password) under Authentication, SMTP. Until then, an admin can reset any password from `/settings/users` (15.6.10).

### 15.3.2 Roles and what each can do
Roles come from `profiles.role` (A.12.1).

| Area | admin | caller (Aditya) | viewer |
|---|---|---|---|
| Today: see send list | yes | yes | yes (no send buttons) |
| Today: mark sent, skip, wrong contact | yes | yes | no |
| Leads list, filters, saved views | yes | yes | yes |
| Leads: bulk change stage, assign owner | yes | stage only | no |
| Leads: CSV export | yes (with money) | yes (no money) | no |
| Lead page: everything except money | yes | yes | read only |
| Lead page: deal value, proposal upload | yes | **never visible** | **never visible** |
| Edit message, request regenerate | yes | yes | no |
| Pipeline board drag | yes | yes | read only |
| Insights: rates and funnels | yes | yes | yes |
| Insights: costs and money | yes | no | no |
| Engine page | yes | no | no |
| Inbox page | yes | no | no |
| Settings: own profile and password | yes | yes | yes |
| Settings: users, roles, suppression | yes | no | no |

The sidebar shows only allowed pages. RLS (Step 2) enforces the same rules in the database.

### 15.3.3 The first admin user
Created in Step 2 seed, or by hand:
1. Supabase dashboard, Authentication, Users, **Add user**: founder's email, a strong password, tick **Auto confirm user**.
2. SQL editor:
   ```sql
   insert into public.profiles (user_id, full_name, role)
   select id, 'Founder', 'admin' from auth.users where email = '<founder email>'
   on conflict (user_id) do update set role = 'admin';
   ```

### 15.3.4 Creating more users from the app (`/settings/users`)
`src/app/(app)/settings/users/actions.ts`:
```ts
'use server'
import { z } from 'zod'
import { revalidatePath } from 'next/cache'
import { requireRole } from '@/lib/auth'
import { createAdminClient } from '@/lib/supabase/admin'

const NewUser = z.object({
  email: z.string().email(),
  fullName: z.string().min(2).max(80),
  role: z.enum(['admin', 'caller', 'viewer']),
})

export async function createUser(input: z.infer<typeof NewUser>) {
  await requireRole(['admin'])
  const data = NewUser.parse(input)
  const tempPassword = generateTempPassword()              // 16 chars, all character classes
  const admin = createAdminClient()
  const { data: created, error } = await admin.auth.admin.createUser({
    email: data.email,
    password: tempPassword,
    email_confirm: true,
    user_metadata: { full_name: data.fullName, must_change_password: true },
  })
  if (error) return { ok: false as const, message: error.message }
  await admin.from('profiles').upsert({ user_id: created.user.id, full_name: data.fullName, role: data.role })
  revalidatePath('/settings/users')
  return { ok: true as const, tempPassword }               // shown ONCE in a dialog, never stored
}

export async function setRole(userId: string, role: 'admin' | 'caller' | 'viewer') {
  const me = await requireRole(['admin'])
  if (me.user.id === userId && role !== 'admin') return { ok: false as const, message: 'You cannot remove your own admin role.' }
  await createAdminClient().from('profiles').update({ role }).eq('user_id', userId)
  revalidatePath('/settings/users')
  return { ok: true as const }
}

export async function disableUser(userId: string) {
  await requireRole(['admin'])
  await createAdminClient().auth.admin.updateUserById(userId, { ban_duration: '876000h' }) // about 100 years
  revalidatePath('/settings/users')
  return { ok: true as const }
}

export async function resetPasswordForUser(userId: string) {
  await requireRole(['admin'])
  const tempPassword = generateTempPassword()
  await createAdminClient().auth.admin.updateUserById(userId, {
    password: tempPassword,
    user_metadata: { must_change_password: true },
  })
  return { ok: true as const, tempPassword }
}

function generateTempPassword() {
  const sets = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnpqrstuvwxyz', '23456789', '!@#$%^&*?']
  const all = sets.join('')
  const pick = (s: string) => s[crypto.getRandomValues(new Uint32Array(1))[0] % s.length]
  const chars = [...sets.map(pick), ...Array.from({ length: 12 }, () => pick(all))]
  return chars.sort(() => crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32 - 0.5).join('')
}
```
Flow for a new teammate:
1. Admin fills email, name, role and clicks **Create**.
2. A dialog shows the temporary password once, with a **Copy** button. The admin shares it privately.
3. On first login, middleware sends the user to `/settings?change_password=1` until they set a new password, and the action clears `must_change_password`.

### 15.3.5 Login page (`/login`)
`src/app/(auth)/login/actions.ts`:
```ts
'use server'
import { z } from 'zod'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

const Login = z.object({ email: z.string().email(), password: z.string().min(1), next: z.string().optional() })

export async function login(_: unknown, formData: FormData) {
  const parsed = Login.safeParse(Object.fromEntries(formData))
  if (!parsed.success) return { message: 'Enter your email and password.' }
  const supabase = await createClient()
  const { error } = await supabase.auth.signInWithPassword({ email: parsed.data.email, password: parsed.data.password })
  if (error) return { message: 'Email or password is not right.' }   // never say which one
  const next = parsed.data.next?.startsWith('/') ? parsed.data.next : '/'
  redirect(next)
}

export async function logout() {
  const supabase = await createClient()
  await supabase.auth.signOut()
  redirect('/login')
}
```
Page layout (Nument kit, calm):
- Centred column, max width 380px, white surface, hairline border `--color-st-secondary`, radius `--radius-2xl`.
- Wordmark "nument" at the top, title "Sign in" in Newsreader 28px, email and password inputs (radius full, as in the kit), primary button "Sign in", link "Forgot password?" to `/reset-password`.
- Error message in plain text under the button (`--red-600`), no shaking or animations.
- `useActionState` (React 19) to show the returned message without a page reload.

### 15.3.6 Forgot and reset password
1. `/reset-password` page: one email field. Action:
   ```ts
   'use server'
   import { createClient } from '@/lib/supabase/server'
   export async function requestReset(_: unknown, formData: FormData) {
     const email = String(formData.get('email') ?? '')
     const supabase = await createClient()
     await supabase.auth.resetPasswordForEmail(email, {
       redirectTo: `${process.env.NEXT_PUBLIC_APP_URL}/auth/confirm?next=/reset-password/update`,
     })
     // Same message whether or not the email exists.
     return { message: 'If this email has an account, a reset link is on its way.' }
   }
   ```
2. `/auth/confirm/route.ts` verifies the link and creates the session:
   ```ts
   import { type NextRequest, NextResponse } from 'next/server'
   import type { EmailOtpType } from '@supabase/supabase-js'
   import { createClient } from '@/lib/supabase/server'

   export async function GET(request: NextRequest) {
     const { searchParams, origin } = new URL(request.url)
     const token_hash = searchParams.get('token_hash')
     const type = searchParams.get('type') as EmailOtpType | null
     const next = searchParams.get('next') ?? '/'
     if (token_hash && type) {
       const supabase = await createClient()
       const { error } = await supabase.auth.verifyOtp({ type, token_hash })
       if (!error) return NextResponse.redirect(`${origin}${next.startsWith('/') ? next : '/'}`)
     }
     return NextResponse.redirect(`${origin}/login?error=link`)
   }
   ```
3. `/reset-password/update` page: new password + confirm. Action calls `supabase.auth.updateUser({ password, data: { must_change_password: false } })`, then redirects to `/`.

### 15.3.7 Password rules (same schema everywhere)
`src/lib/password.ts`:
```ts
import { z } from 'zod'
export const PasswordSchema = z.string()
  .min(12, 'Use at least 12 characters.')
  .regex(/[a-z]/, 'Add a lowercase letter.')
  .regex(/[A-Z]/, 'Add an uppercase letter.')
  .regex(/[0-9]/, 'Add a number.')
  .regex(/[^A-Za-z0-9]/, 'Add a symbol.')
```
The Supabase dashboard enforces the same rules on the server (15.3.1 step 4), so the form check is only for friendly messages.

### 15.3.8 Sessions
- Cookies are set by `@supabase/ssr`: httpOnly, `SameSite=Lax`, `Secure` in prod.
- Access tokens last 1 hour by default and are refreshed by the middleware on each request.
- **Log out** is in the user menu (calls `logout`).
- Server Actions check the session again (`requireRole`) even though the middleware already did. Never skip this.

### 15.3.9 Optional later: two-factor login (TOTP)
When the team grows, add an authenticator-app step:
1. `/settings` gets "Turn on two-factor": `supabase.auth.mfa.enroll({ factorType: 'totp' })` returns a QR code to scan.
2. After login, if the user has a factor, call `mfa.challenge` and `mfa.verify` before showing the app.
3. Add an RLS check on sensitive tables for `aal2` (Supabase docs: "Enforce MFA with RLS").
Not needed for go-live.

---

## 15.4 Design system (Nument kit)

### 15.4.1 Copy the tokens
```bash
$ mkdir -p web/src/styles
$ cp ~/Desktop/Extra/sarvam-design-kit/tokens/tokens.css web/src/styles/tokens.css
```
Then edit `web/src/styles/tokens.css`:
1. **Delete the Google Fonts `@import url(...)` line.** `next/font` loads the fonts (faster, no layout shift).
2. Keep every other variable as it is (`--color-*`, `--indigo-*`, `--grey-*`, `--green-*`, `--red-*`, `--yellow-*`, `--pink-*`, `--orange-*`, `--radius-*`, `--shadow-*`, `--ease-*`, `--dur-*`).

### 15.4.2 Fonts with `next/font`
`src/app/layout.tsx`:
```tsx
import type { Metadata } from 'next'
import { Newsreader, Figtree, DM_Mono } from 'next/font/google'
import { Toaster } from 'sonner'
import './globals.css'

const display = Newsreader({ subsets: ['latin'], variable: '--nf-display', axes: ['opsz'], display: 'swap' })
const sans = Figtree({ subsets: ['latin'], variable: '--nf-sans', display: 'swap' })
const mono = DM_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--nf-mono', display: 'swap' })

export const metadata: Metadata = { title: 'Nument Leads', robots: { index: false, follow: false } }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        {children}
        <Toaster position="bottom-right" closeButton />
      </body>
    </html>
  )
}
```
- `robots: noindex` because this is a private tool.

### 15.4.3 Tailwind mapping
Next's generator installs Tailwind v4 (CSS-first). Map the kit tokens in `src/app/globals.css`:
```css
@import "../styles/tokens.css";
@import "tailwindcss";

:root {
  --font-display: var(--nf-display), Georgia, serif;
  --font-sans: var(--nf-sans), system-ui, sans-serif;
  --font-mono: var(--nf-mono), ui-monospace, monospace;
}

@theme inline {
  --font-display: var(--font-display);
  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);

  --color-tx: var(--color-tx);
  --color-tx-2: var(--color-tx-secondary);
  --color-tx-3: var(--color-tx-tertiary);
  --color-tx-muted: var(--color-tx-muted);
  --color-bg: var(--color-bg);
  --color-surface: var(--color-sf-white);
  --color-surface-2: var(--color-sf-secondary);
  --color-line: var(--color-st);
  --color-line-2: var(--color-st-secondary);
  --color-ink: var(--color-ink);

  --color-indigo-50: var(--indigo-50);   --color-indigo-100: var(--indigo-100);
  --color-indigo-200: var(--indigo-200); --color-indigo-300: var(--indigo-300);
  --color-indigo-600: var(--indigo-600); --color-indigo-700: var(--indigo-700);
  --color-indigo-800: var(--indigo-800); --color-indigo-900: var(--indigo-900);

  --color-ok: var(--green-700);    --color-ok-bg: var(--green-100);
  --color-warn: var(--yellow-700); --color-warn-bg: var(--yellow-50);
  --color-bad: var(--red-600);     --color-bad-bg: var(--red-50);

  --radius-sm: var(--radius-md);
  --radius-md: var(--radius-lg);
  --radius-lg: var(--radius-xl);
  --radius-card: var(--radius-2xl);
}

body {
  background: var(--color-bg);
  color: var(--color-tx);
  font-family: var(--font-sans);
  font-weight: var(--fw-regular);
  font-size: 14px;
  -webkit-font-smoothing: antialiased;
}
.label-mono {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--color-tx-tertiary);
}
:focus-visible { outline: 2px solid var(--indigo-400); outline-offset: 2px; }
```
If your setup installed Tailwind v3 instead, put the same mapping in `tailwind.config.ts` under `theme.extend` (colors, fontFamily, borderRadius) pointing at the same CSS variables.

### 15.4.4 Design rules (follow the founder's taste)
1. Near-white page (`--color-bg`), white surfaces, **hairline borders** (`--color-st-secondary`). No heavy shadows; at most `--shadow-sm` on menus and dialogs.
2. **Indigo only for primary actions, links, focus and the selected nav item.** Everything else is grey text on white.
3. Primary button uses the kit ink gradient (`--gradient-btn-primary` + `--shadow-btn-ink`). Secondary buttons are white with a 1px border. Buttons are fully rounded (`--radius-full`), as in the kit.
4. **No floating cards, no decorative pills, no gradients on surfaces, no emoji.** Badges are small flat rectangles (radius 6px) in the stage colours from A.12.2.
5. Type scale: page titles Newsreader 28px; section titles Figtree 15px medium; body 14px; meta 12px; labels DM Mono 11px uppercase (`.label-mono`).
6. Density: table rows 44px, 12px cell padding, sticky table header.
7. Numbers in KPI tiles use Newsreader 32px in `--indigo-900`; money in `--green-800`.
8. Dates: "12 Nov, 4:30 pm" (IST). Relative age for signals: "3 days ago".
9. Empty states are one calm sentence plus one action, never an illustration.

### 15.4.5 Stage and grade constants
`src/lib/stages.ts` (values copied from A.12.2):
```ts
export const STAGES = [
  { value: 'new',              label: 'New',              closed: false, bg: '#F2F2F2', fg: '#525252' },
  { value: 'contacted',        label: 'Contacted',        closed: false, bg: '#E8EFFC', fg: '#212191' },
  { value: 'talking',          label: 'Talking',          closed: false, bg: '#D2DFF9', fg: '#11115B' },
  { value: 'discovery_booked', label: 'Discovery booked', closed: false, bg: '#FCEAF0', fg: '#9D2055' },
  { value: 'discovery_done',   label: 'Discovery done',   closed: false, bg: '#F9D5E1', fg: '#871F4B' },
  { value: 'proposal_sent',    label: 'Proposal sent',    closed: false, bg: '#FFF0CF', fg: '#8A5A00' },
  { value: 'won',              label: 'Won',              closed: true,  bg: '#E3F1D8', fg: '#385418' },
  { value: 'retainer',         label: 'Retainer',         closed: true,  bg: '#D9F0EA', fg: '#0F5C52' },
  { value: 'lost',             label: 'Lost',             closed: true,  bg: '#FDE7E2', fg: '#A21913' },
  { value: 'not_now',          label: 'Not now',          closed: true,  bg: '#FEEDE6', fg: '#A5460F' },
  { value: 'not_a_fit',        label: 'Not a fit',        closed: true,  bg: '#F5F5F5', fg: '#999999' },
  { value: 'wrong_contact',    label: 'Wrong contact',    closed: true,  bg: '#F3EEE8', fg: '#7A5536' },
] as const
export type Stage = (typeof STAGES)[number]['value']
export const stageOf = (v: string) => STAGES.find((s) => s.value === v) ?? STAGES[0]
export const OPEN_STAGES = STAGES.filter((s) => !s.closed).map((s) => s.value)
```
`src/lib/grades.ts`:
```ts
export const GRADE_STYLE = {
  A: { bg: '#E3F1D8', fg: '#496D21' },
  B: { bg: '#E8EFFC', fg: '#3333CC' },
  C: { bg: '#F5F5F5', fg: '#666666' },
  D: { bg: '#FAFAFA', fg: '#999999' },
} as const
```

### 15.4.6 Base components (skeletons)
`src/components/ui/button.tsx`:
```tsx
import { forwardRef } from 'react'
import { cn } from '@/lib/cn'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

export const Button = forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }>(
  function Button({ variant = 'secondary', size = 'md', className, ...props }, ref) {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors disabled:opacity-50',
          size === 'sm' ? 'h-8 px-3 text-[13px]' : 'h-10 px-4 text-[14px]',
          variant === 'primary' && 'text-white [background:var(--gradient-btn-primary)] [box-shadow:var(--shadow-btn-ink)]',
          variant === 'secondary' && 'bg-surface text-tx border border-line hover:bg-surface-2',
          variant === 'ghost' && 'text-tx-2 hover:bg-surface-2',
          variant === 'danger' && 'bg-surface text-bad border border-line hover:bg-bad-bg',
          className,
        )}
        {...props}
      />
    )
  },
)
```
`src/components/ui/badge.tsx`:
```tsx
import { stageOf } from '@/lib/stages'
import { GRADE_STYLE } from '@/lib/grades'

export function StageBadge({ stage }: { stage: string }) {
  const s = stageOf(stage)
  return (
    <span className="inline-flex h-6 items-center rounded-[6px] px-2 text-[12px] font-medium"
          style={{ background: s.bg, color: s.fg }}>{s.label}</span>
  )
}

export function GradeBadge({ grade }: { grade: 'A' | 'B' | 'C' | 'D' }) {
  const g = GRADE_STYLE[grade]
  return (
    <span className="inline-flex h-6 w-6 items-center justify-center rounded-[6px] text-[12px] font-semibold"
          style={{ background: g.bg, color: g.fg }}>{grade}</span>
  )
}
```
`src/components/ui/kpi-tile.tsx`:
```tsx
export function KpiTile({ label, value, hint, tone = 'default' }:
  { label: string; value: string | number; hint?: string; tone?: 'default' | 'money' | 'alert' }) {
  const color = tone === 'money' ? 'var(--green-800)' : tone === 'alert' ? 'var(--red-600)' : 'var(--indigo-900)'
  return (
    <div className="rounded-[var(--radius-xl)] border border-line-2 bg-surface px-4 py-3">
      <div className="label-mono">{label}</div>
      <div className="mt-1 font-display text-[32px] leading-none" style={{ color }}>{value}</div>
      {hint && <div className="mt-1 text-[12px] text-tx-3">{hint}</div>}
    </div>
  )
}
```
`src/components/ui/empty-state.tsx`:
```tsx
export function EmptyState({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-[var(--radius-xl)] border border-dashed border-line px-6 py-10 text-center">
      <p className="text-tx-3">{text}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
```
Other primitives, same style rules:
| Component | Built on | Notes |
|---|---|---|
| `Card` | `div` | White, 1px `line-2` border, radius 16px, padding 16px. Title row uses `label-mono`. |
| `Table` | `table` | Sticky header (`label-mono`), 44px rows, row hover `surface-2`. |
| `Tabs` | `@radix-ui/react-tabs` | Kit style: inactive grey text, active ink text with a 2px indigo underline. |
| `Drawer` | `@radix-ui/react-dialog` | Slides from the right on desktop (lead quick view), full screen on mobile. |
| `Input`, `Select`, `Textarea` | native + Radix Select | 40px height, radius 10px, focus ring indigo. |
| `Toaster` | `sonner` | Bottom right. Messages in plain words. Undo actions use the toast action button. |

### 15.4.7 Layout shell
`src/app/(app)/layout.tsx`:
```tsx
import { redirect } from 'next/navigation'
import { getSessionUser } from '@/lib/auth'
import { Sidebar } from '@/components/shell/sidebar'
import { Topbar } from '@/components/shell/topbar'

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const s = await getSessionUser()
  if (!s) redirect('/login')
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[224px_1fr]">
      <Sidebar role={s.role} />
      <div className="min-w-0">
        <Topbar name={s.name} role={s.role} env={process.env.APP_ENV ?? 'dev'} />
        <main className="mx-auto max-w-[1280px] px-4 pb-16 pt-6 md:px-8">{children}</main>
      </div>
    </div>
  )
}
```
Sidebar items (filtered by role):
| Label | Path | Roles |
|---|---|---|
| Today | `/` | all |
| Leads | `/leads` | all |
| Pipeline | `/pipeline` | all |
| Insights | `/insights` | all |
| Engine | `/engine` | admin |
| Inbox | `/inbox` | admin |
| Settings | `/settings` | all |

- Desktop: fixed left sidebar, wordmark "nument" at the top, items in Figtree 14px, active item ink text with an indigo 2px left bar.
- Mobile (under 768px): sidebar collapses to a top bar with a menu button that opens a Drawer.
- Top bar: page title slot, "DEV" badge (amber flat rectangle) when `APP_ENV=dev`, "Sheet synced 10:15 am" (latest `runs` row with `kind = 'sheet_sync'` and `status = 'ok'`), user menu (profile, log out).

---

## 15.5 Data layer

### 15.5.1 Views and tables the app reads
The app reads these database objects. Step 2 creates them. Views must be created `with (security_invoker = true)` so RLS applies to the person asking, except `v_leads_admin`, which filters to admins itself.

| Object | Used on | Columns the app needs |
|---|---|---|
| `v_today` | Today | `lead_id`, `business_id`, `company`, `city`, `country`, `segment_id`, `grade`, `total`, `pitch_mode`, `angle`, `top_signal_type`, `top_signal_quote`, `top_signal_url`, `top_signal_at`, `contact_name`, `contact_role`, `phone_e164`, `phone_type`, `phone_source`, `message`, `created_at`. Rows: stage `new`, grade A or B, not suppressed, `skipped_until` empty or past. |
| `v_leads_caller` | Leads list, lead page for callers and viewers | Every `leads` column **except** `deal_value_inr`, joined with `businesses` (`name`, `city`, `country`, `segment_id`, `website`, `category`) and the top signal. |
| `v_leads_admin` | Leads list, lead page for admins | Same as `v_leads_caller` plus `deal_value_inr`. Returns no rows unless the caller's role is `admin`. |
| `v_followups_due` | Today | `lead_id`, `company`, `phone_e164`, `which` (`d3` or `d7`), `followup_text`, `due_on`. |
| `v_funnel` | Insights | One row per lead with `segment_id`, `country`, `pitch_mode`, `angle`, `test_group`, `top_signal_type`, `created_on`, and booleans `reached_contacted`, `reached_talking`, `reached_discovery`, `reached_proposal`, `reached_won`. |
| `v_costs_daily` | Insights, Engine | `day`, `provider`, `task`, `inr`, `calls`. Admin only. |
| tables | Lead page | `signals`, `facts` (`verified = true` by default), `contacts`, `scores`, `activities`, `feedback`, `pages` (titles and URLs only) |
| tables | Engine, Inbox, Settings | `segments`, `settings`, `source_health`, `runs`, `custom_queries`, `inbox_posts`, `suppression`, `profiles` |
| table `saved_views` | Leads | `id`, `user_id`, `name`, `query` (jsonb), `shared`, `created_at` (new, see 15.13) |

Writes:
- Callers and admins update **only these `leads` columns**: `stage`, `wa_at`, `call_at`, `d3_at`, `d7_at`, `meeting_at`, `next_step`, `due_at`, `notes`, `message`, `message_alt`, `followup_d3`, `followup_d7`, `owner_id` (admin), `skipped_until`, `regen_requested_at`, `last_activity_at`, `updated_at`. Step 2 grants column-level `update` on exactly these.
- `deal_value_inr` is written only by admin Server Actions with the admin client after `requireRole(['admin'])`.

### 15.5.2 Query modules
One file per page in `src/lib/queries/`, all `import 'server-only'`. Example `src/lib/queries/today.ts`:
```ts
import 'server-only'
import { createClient } from '@/lib/supabase/server'

export async function getTodaySendList(limit = 100) {
  const supabase = await createClient()
  const { data, error } = await supabase
    .from('v_today')
    .select('*')
    .order('grade', { ascending: true })      // A before B
    .order('total', { ascending: false })
    .order('created_at', { ascending: false })
    .limit(limit)
  if (error) throw error
  return data
}

export async function getTodayKpis() {
  const supabase = await createClient()
  const weekStart = startOfWeekIST()           // Monday 00:00 IST as UTC ISO
  const head = { count: 'exact' as const, head: true }
  const [ready, contacted, talking, discovery, proposals, overdue] = await Promise.all([
    supabase.from('v_today').select('lead_id', head),
    supabase.from('activities').select('id', head).eq('type', 'sent').gte('at', weekStart),
    supabase.from('v_leads_caller').select('id', head).eq('stage', 'talking'),
    supabase.from('v_leads_caller').select('id', head).in('stage', ['discovery_booked', 'discovery_done']),
    supabase.from('v_leads_caller').select('id', head).eq('stage', 'proposal_sent'),
    supabase.from('v_leads_caller').select('id', head).lt('due_at', new Date().toISOString())
      .not('stage', 'in', '(won,retainer,lost,not_now,not_a_fit,wrong_contact)'),
  ])
  return {
    ready: ready.count ?? 0, contacted: contacted.count ?? 0, talking: talking.count ?? 0,
    discovery: discovery.count ?? 0, proposals: proposals.count ?? 0, overdue: overdue.count ?? 0,
  }
}
```
Choose the view by role:
```ts
export const leadsView = (role: 'admin' | 'caller' | 'viewer') => (role === 'admin' ? 'v_leads_admin' : 'v_leads_caller')
```

### 15.5.3 Activity logging
`src/lib/activity.ts`:
```ts
import 'server-only'
import type { SupabaseClient } from '@supabase/supabase-js'

export type ActivityType =
  | 'sent' | 'followup_sent' | 'stage_change' | 'edit' | 'note' | 'skip' | 'wrong_contact'
  | 'feedback' | 'proposal_upload' | 'regen_request' | 'undo'

export async function logActivity(sb: SupabaseClient, leadId: string, userId: string,
  type: ActivityType, payload: Record<string, unknown> = {}) {
  await sb.from('activities').insert({ lead_id: leadId, user_id: userId, source: 'app', type, payload })
  await sb.from('leads').update({ last_activity_at: new Date().toISOString() }).eq('id', leadId)
}
```
Every Server Action that changes a lead calls `logActivity` with a `payload` describing the change, for example `{ field: 'stage', from: 'new', to: 'contacted' }`.

### 15.5.4 Server Action pattern
Every action follows the same five steps:
1. `requireRole([...])`.
2. Validate input with zod.
3. Write with the **user session** client (RLS checks it again).
4. `logActivity(...)`.
5. `revalidatePath(...)` for every page that shows the data, and return `{ ok, message? }`.

Example, change stage (`src/app/(app)/leads/[id]/actions.ts`):
```ts
'use server'
import { z } from 'zod'
import { revalidatePath } from 'next/cache'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { logActivity } from '@/lib/activity'
import { STAGES } from '@/lib/stages'

const StageInput = z.object({ leadId: z.string().uuid(), stage: z.enum(STAGES.map((s) => s.value) as [string, ...string[]]) })

export async function updateStage(input: z.infer<typeof StageInput>) {
  const s = await requireRole(['admin', 'caller'])
  const { leadId, stage } = StageInput.parse(input)
  const sb = await createClient()
  const { data: before } = await sb.from('v_leads_caller').select('stage, wa_at').eq('id', leadId).single()
  if (!before) return { ok: false as const, message: 'Lead not found.' }

  const patch: Record<string, unknown> = { stage, updated_at: new Date().toISOString() }
  if (stage === 'contacted' && !before.wa_at) patch.wa_at = new Date().toISOString()   // same rule as the sheet (D-043)
  const { error } = await sb.from('leads').update(patch).eq('id', leadId)
  if (error) return { ok: false as const, message: 'Could not save. Try again.' }

  await logActivity(sb, leadId, s.user.id, 'stage_change', { from: before.stage, to: stage })
  revalidatePath('/'); revalidatePath('/leads'); revalidatePath(`/leads/${leadId}`); revalidatePath('/pipeline')
  return { ok: true as const }
}
```

### 15.5.5 Refresh strategy
| Page | Strategy |
|---|---|
| Today | Server-rendered. Client component calls `router.refresh()` every 60 seconds while the tab is visible, and on window focus. |
| Pipeline | Same as Today, plus optimistic moves (`useOptimistic`) so a dragged card lands instantly. |
| Lead page | Server-rendered; actions call `revalidatePath`. No polling. |
| Leads list | Server-rendered by URL search params; no polling. |
| Insights, Engine | Server-rendered; "Refresh" button. |

Supabase Realtime is optional. To turn it on later: add `leads` and `activities` to the `supabase_realtime` publication, subscribe with the browser client to `postgres_changes` on `leads` (RLS still applies), and call `router.refresh()` on events. Polling is enough for two or three users.

### 15.5.6 Optimistic updates and undo
- Stage changes on the Pipeline and "Mark sent" on Today update the UI first (`useOptimistic`), then call the action. On failure, the UI reverts and a toast says "Could not save. Try again."
- "Mark sent" and "Wrong contact" show a toast with **Undo** for 8 seconds. Undo calls `undoLeadChange(leadId, previous)` which restores the previous `stage`, `wa_at` and `skipped_until`, and logs an `undo` activity.

### 15.5.7 Staying in sync with the Google Sheet
- The app writes only to the database.
- The sheet sync (Step 13) runs hourly in the daytime and after the morning run. It pushes database changes to the sheet and pulls sheet edits into the database. Edits from the sheet arrive as activities with `source = 'sheet'`.
- If the same field was edited in both places between two syncs, Step 13's rule decides (latest edit wins) and logs it. The app shows the source of every change in the timeline (`app`, `sheet`, `engine`).
- The top bar shows the last successful sheet sync time so nobody wonders why the sheet looks older.

---

## 15.6 Pages

Each page lists: who can open it, what it shows, where the data comes from, and what the user can do.

### 15.6.1 `/login`
- **Who:** anyone not logged in.
- **Shows:** email, password, Sign in, Forgot password link. If the URL has `?error=link`, shows "That link has expired. Ask for a new one."
- **Actions:** `login`, then redirect to `next` or `/`.

### 15.6.2 `/reset-password` and `/reset-password/update`
- **Who:** anyone.
- **Shows:** step 1, an email field and "Send reset link". Step 2 (after the email link), new password and confirm.
- **Actions:** `requestReset`, `/auth/confirm`, then `updatePassword`.

### 15.6.3 `/` Today
- **Who:** all roles. Send buttons only for admin and caller.
- **Layout (top to bottom):**
  1. Title "Today", date in IST on the right ("Thu 12 Nov").
  2. KPI tiles (one row on desktop, two columns on mobile): **Ready to send**, **Contacted this week**, **Talking**, **Discovery**, **Proposals**, **Overdue** (red when above 0). Admins also see **Won this month** in rupees.
  3. **Send list** (from `v_today`), best first.
  4. **Follow-ups due today** (from `v_followups_due`).
- **Send list row:**
  | Part | Content |
  |---|---|
  | Left | Grade badge, company (bold), city, segment label in `label-mono` |
  | Why now | Top signal in plain words plus age ("Hiring a receptionist · 4 days ago"), link icon to the evidence |
  | Contact | Name and role if known, phone (formatted, for example +91 98110 12345), phone type and source ("mobile · website") |
  | Message | First 120 characters, click to expand the full message |
  | Buttons | **Open WhatsApp Web**, **Open WhatsApp app**, **Copy message**, **Mark sent**, **Skip**, **Wrong contact** |
- **Button behaviour:**
  - **Open WhatsApp Web** and **Open WhatsApp app**: open the link in a new tab **synchronously inside the click handler** (so the browser does not block it), then call `markContacted(leadId, channel)` in the background. One tap = WhatsApp opens with the message typed **and** the lead is marked Contacted with `wa_at` set and a `sent` activity. A toast says "Marked as contacted · Undo".
  - **Copy message**: copies the text, no database change.
  - **Mark sent**: same as the WhatsApp buttons without opening anything (for when the founder sent from his phone).
  - **Skip**: sets `skipped_until` to 7 days from now, logs `skip`. The row disappears from Today.
  - **Wrong contact**: stage `wrong_contact`, adds the phone to `suppression` with reason `wrong_contact`, sets `contacts.do_not_contact = true` for that phone, logs `wrong_contact`. Undo is available.
  - On mobile (detected by `navigator.userAgent` in the client component), the **Open WhatsApp app** button is shown first.
- **Actions file** `src/app/(app)/actions.ts`:
  ```ts
  'use server'
  import { revalidatePath } from 'next/cache'
  import { requireRole } from '@/lib/auth'
  import { createClient } from '@/lib/supabase/server'
  import { logActivity } from '@/lib/activity'

  export async function markContacted(leadId: string, channel: 'web' | 'app' | 'manual') {
    const s = await requireRole(['admin', 'caller'])
    const sb = await createClient()
    const { data: before } = await sb.from('v_leads_caller').select('stage, wa_at, skipped_until').eq('id', leadId).single()
    if (!before) return { ok: false as const, message: 'Lead not found.' }
    const now = new Date().toISOString()
    await sb.from('leads').update({
      stage: before.stage === 'new' ? 'contacted' : before.stage,
      wa_at: before.wa_at ?? now,
      updated_at: now,
    }).eq('id', leadId)
    await logActivity(sb, leadId, s.user.id, 'sent', { channel })
    revalidatePath('/'); revalidatePath('/pipeline')
    return { ok: true as const, previous: before }
  }
  ```
- **WhatsApp links** `src/lib/whatsapp.ts`:
  ```ts
  export function waLinks(phoneE164: string, text: string) {
    const digits = phoneE164.replace(/\D/g, '')      // "+919811012345" -> "919811012345"
    const t = encodeURIComponent(text)
    return {
      web: `https://web.whatsapp.com/send?phone=${digits}&text=${t}`,  // desktop, opens WhatsApp Web directly
      app: `https://wa.me/${digits}?text=${t}`,                          // phone, opens the WhatsApp app
    }
  }
  ```
- **Client button** (`src/components/today/wa-buttons.tsx`, key part):
  ```tsx
  'use client'
  import { toast } from 'sonner'
  import { markContacted, undoLeadChange } from '@/app/(app)/actions'

  export function OpenWhatsApp({ leadId, href, channel, label }: { leadId: string; href: string; channel: 'web' | 'app'; label: string }) {
    return (
      <button
        className="btn-primary-sm"
        onClick={() => {
          window.open(href, '_blank', 'noopener')          // must happen before any await
          markContacted(leadId, channel).then((r) => {
            if (!r.ok) return toast.error(r.message)
            toast('Marked as contacted', { action: { label: 'Undo', onClick: () => undoLeadChange(leadId, r.previous) }, duration: 8000 })
          })
        }}
      >{label}</button>
    )
  }
  ```
- **Empty state:** "Nothing new to send today. The engine adds leads every morning by 7:30 am."

### 15.6.4 `/leads` Leads list
- **Who:** all roles. Bulk actions for admin and caller (caller: stage only).
- **Data:** `v_leads_admin` (admin) or `v_leads_caller` (others). Server-side filtering, sorting and pagination driven by URL search params, so every view is shareable as a link.
- **Columns (TanStack Table, column chooser saved per user):**
  select box, Grade, Company, Segment, Country, City, Stage, Top signal, Score, Pitch mode, Phone type, Owner, Last activity, Due, Deal value (admin only).
- **Filters (left panel on desktop, Drawer on mobile):**
  | Filter | Control | Query |
  |---|---|---|
  | Segment | multi-select from `segments` | `.in('segment_id', [...])` |
  | Country | multi-select | `.in('country', [...])` |
  | City | multi-select (depends on country) | `.in('city', [...])` |
  | Grade | A B C D toggles | `.in('grade', [...])` |
  | Signal type | multi-select from A.12.3 | `.in('top_signal_type', [...])` |
  | Stage | multi-select | `.in('stage', [...])` |
  | Pitch mode | stated_need, visible_pain, fit_only | `.in('pitch_mode', [...])` |
  | Has mobile | toggle | `.eq('phone_type', 'mobile')` |
  | Added | date range | `.gte('created_at', from).lte('created_at', to)` |
- **Search box:** company name, phone digits or website domain (`.or('name.ilike.%q%,phone_e164.ilike.%q%,web_domain.ilike.%q%')`). Step 2 adds a trigram index on `businesses.norm_name` for speed.
- **Pagination:** 50 rows per page, `range(from, to)` with `count: 'exact'`.
- **Saved views:** "Save view" stores the current URL query in `saved_views` (name, query, shared flag). The left panel lists "My views" and "Shared views".
- **Bulk bar** (appears when rows are selected): Change stage, Assign owner (admin), Add to suppression (admin), Export selected. Each bulk action loops through `updateStage` logic in one Server Action with a single `revalidatePath`, and logs one activity per lead.
- **CSV export** `src/app/(app)/leads/export/route.ts`:
  ```ts
  import { getSessionUser } from '@/lib/auth'
  import { createClient } from '@/lib/supabase/server'
  import { toCsv } from '@/lib/csv'

  export async function GET(request: Request) {
    const s = await getSessionUser()
    if (!s || s.role === 'viewer') return new Response('Not allowed', { status: 403 })
    const sb = await createClient()
    const view = s.role === 'admin' ? 'v_leads_admin' : 'v_leads_caller'
    const query = applyFilters(sb.from(view).select('*'), new URL(request.url).searchParams)  // same helper as the page
    const { data } = await query.limit(5000)
    const csv = toCsv(data ?? [])
    const day = new Date().toISOString().slice(0, 10)
    return new Response(csv, {
      headers: { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': `attachment; filename="leads-${day}.csv"` },
    })
  }
  ```
  Callers' exports never include money because the view has no money column.

### 15.6.5 `/leads/[id]` Lead page
- **Who:** all roles; editing for admin and caller; money only for admin.
- **Data:** one lead from the role's view, plus `contacts`, `signals`, `facts` (verified), latest `scores` row, `activities` (newest first), `feedback`, and `pages` (title and URL) for the business. Fetch in parallel with `Promise.all`.
- **Layout:** two columns on desktop (left 2/3, right 1/3), one column on mobile.

**Header**
- Company name (Newsreader 28px), city, country, segment label, website link.
- Grade badge, score total ("82 / 100").
- Stage dropdown (calls `updateStage`), owner select (admin), next step text and due date (inline edit).

**Contact card (right column, top)**
- Decision maker name and role, with source ("from website, About page").
- Every phone: formatted number, type badge (mobile, landline, toll free), source ("website" or "Google listing"), and the two WhatsApp buttons (same behaviour as Today).
- Email, website, Google listing link (built from `place_id`).
- Do-not-contact phones are shown struck through with the reason.

**Why this lead**
- Score breakdown as four thin horizontal bars: Fit, Can pay, Intent, Reach (values from `scores`), plus the total and grade.
- `reasons` from `scores` as short bullet points (for example "3 branches", "Hiring a receptionist 4 days ago", "No online booking").
- `judge_note` from the top-model judgement, in italics, with the model name in `label-mono`.
- Pitch mode and test group in `label-mono` at the bottom.

**Signals**
- List, newest first: type label, age ("4 days ago"), points, the quote in grey, and a link to the evidence URL. Expired signals are greyed with "expired".

**Facts**
- Grouped by field (Team, Branches, Services, Prices, Booking, Tech, Careers). Each fact shows the value, the quote, and a link to the page. Only `verified = true` facts by default. Admins can toggle "Show unverified".

**Website and tech check**
- Booking method, WhatsApp button, chat widget, CMS, ad pixels (Meta, Google), mobile speed score, with yes or no marks. From `facts` fields written by Step 9.

**Message**
- Textarea with the current `message`, live lint under it (same rules as Step 12 lint: 30 to 60 words target, hard limits 25 to 70, exactly one question mark, no links, no emojis, no dashes, no banned phrases). Lint result: "Looks good" or the list of problems.
- Buttons: **Save** (writes `message`, logs `edit`), **Use alternate** (swaps `message` and `message_alt`), **Regenerate** (sets `regen_requested_at`, logs `regen_request`; the next morning run rewrites it, see Step 12), the two WhatsApp buttons.
- **Follow-ups:** day 3 and day 7 drafts (`followup_d3`, `followup_d7`), editable, each with WhatsApp buttons that set `d3_at` or `d7_at` and log `followup_sent`.

**Activity timeline**
- All `activities`, newest first: icon by type, plain sentence ("Aditya moved stage from Contacted to Talking"), time in IST, source badge (`app`, `sheet`, `engine`).

**Notes**
- Add note box (logs `note` with the text in `payload`). `leads.notes` keeps the latest summary for the sheet's Notes column.

**Deal (admin only)**
- Deal value in rupees (writes `deal_value_inr` through an admin action), currency note for foreign leads.
- Proposal upload: PDF or DOCX, up to 10 MB, stored in the private Storage bucket `proposals` at `{lead_id}/{timestamp}-{filename}`. Downloads use signed URLs valid for 60 seconds. Logs `proposal_upload`.
  ```ts
  'use server'
  export async function uploadProposal(leadId: string, formData: FormData) {
    const s = await requireRole(['admin'])
    const file = formData.get('file') as File | null
    if (!file || file.size > 10 * 1024 * 1024) return { ok: false as const, message: 'Choose a file under 10 MB.' }
    const path = `${leadId}/${Date.now()}-${file.name.replace(/[^\w.-]/g, '_')}`
    const admin = createAdminClient()
    const { error } = await admin.storage.from('proposals').upload(path, file, { contentType: file.type })
    if (error) return { ok: false as const, message: 'Upload failed.' }
    await logActivity(admin, leadId, s.user.id, 'proposal_upload', { path })
    revalidatePath(`/leads/${leadId}`)
    return { ok: true as const }
  }
  ```

**Feedback**
- Thumbs up and thumbs down with a reason select: "Great lead", "Wrong segment", "Cannot pay", "No real need", "Wrong contact", "Already has a vendor", "Other". Writes `feedback` (`rating` 1 or -1) and logs `feedback`. These labels feed Step 16 and the golden set (Step 17).

### 15.6.6 `/pipeline`
- **Who:** all roles; drag for admin and caller.
- **Columns:** open stages in order (Contacted, Talking, Discovery booked, Discovery done, Proposal sent), then closed stages collapsed into narrow columns (Won, Retainer, Lost, Not now, Not a fit, Wrong contact). New leads stay on Today and are not on the board.
- **Card:** company, city, grade badge, next step, due date (red if overdue), deal value (admin), owner initials.
- **Filters:** segment, country, owner, "only overdue".
- **Drag and drop:** `@dnd-kit/core` with `PointerSensor`, `TouchSensor` (press 200 ms) and `KeyboardSensor` (accessible). Dropping a card calls `updateStage` with an optimistic move. Moving to **Won** or **Retainer** as an admin opens a small dialog asking for the deal value.
- Skeleton:
  ```tsx
  'use client'
  import { DndContext, PointerSensor, TouchSensor, KeyboardSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
  import { useOptimistic, startTransition } from 'react'
  import { updateStage } from '@/app/(app)/leads/[id]/actions'

  export function Board({ cards }: { cards: Card[] }) {
    const [items, move] = useOptimistic(cards, (state, m: { id: string; stage: string }) =>
      state.map((c) => (c.id === m.id ? { ...c, stage: m.stage } : c)))
    const sensors = useSensors(useSensor(PointerSensor), useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }), useSensor(KeyboardSensor))
    function onDragEnd(e: DragEndEvent) {
      const stage = e.over?.id as string | undefined
      if (!stage) return
      startTransition(async () => {
        move({ id: String(e.active.id), stage })
        const r = await updateStage({ leadId: String(e.active.id), stage })
        if (!r.ok) toast.error(r.message)
      })
    }
    return <DndContext sensors={sensors} onDragEnd={onDragEnd}>{/* columns */}</DndContext>
  }
  ```

### 15.6.7 `/insights`
- **Who:** all roles; cost and money sections admin only.
- **Filters:** date range (default last 30 days), segment, country.
- **Sections:**
  1. **Funnel** (from `v_funnel`): Contacted, Talking, Discovery, Proposal, Won, as counts and percent of contacted. A small bar chart per segment.
  2. **What works** table: rows grouped by a selector (Segment, Country, Signal type, Pitch mode, Angle, Test group). Columns: contacted, reply rate (talking or later), meeting rate (discovery or later), win rate. Rows with fewer than 30 contacted are greyed with "too few to judge".
  3. **Lead quality:** own phone found percent, wrong contact percent, median signal age, feedback thumbs up percent.
  4. **Cost (admin):** spend per day line chart against the ₹750 cap (from `v_costs_daily`), cost per researched business, cost per good lead, cost per won client.
- **Charts:** recharts with kit colours (indigo 600 for main series, grey 300 for comparison), no gridline clutter (only horizontal light lines), Figtree tick labels, values in tooltips.
- Rates use the same definitions as the weekly report (Step 16) so numbers never disagree.

### 15.6.8 `/engine` (admin only)
- **Segments:** table of `segments` with an **Enabled** toggle and a **Daily quota** number field (writes `segments.enabled`, `segments.daily_quota`, and mirrors into `settings.segments_enabled`). Shows yesterday's researched and lead counts per segment.
- **Budget:** fields for `daily_cap_inr` (default 750), `alert_pct` (80), `research_per_day` (300). A gauge shows today's spend against the cap (from `costs`).
- **Sources:** `source_health` table: enabled toggle (kill switch), last ok, last error, blocked until, requests today. A blocked source shows in red with its error.
- **Runs:** last 20 `runs`: kind, started (IST), duration, status badge, key stats (researched, leads, cost), error text if failed.
- **Run now:** buttons **Run night**, **Run morning**, **Sync sheet** with options (dry run, limit, segment). They trigger GitHub Actions:
  ```ts
  'use server'
  import { requireRole } from '@/lib/auth'

  const WORKFLOWS = { night: 'night.yml', morning: 'morning.yml', sheet: 'sheet-sync.yml' } as const

  export async function triggerRun(kind: keyof typeof WORKFLOWS, opts: { dryRun: boolean; limit?: number; segment?: string }) {
    await requireRole(['admin'])
    const res = await fetch(
      `https://api.github.com/repos/${process.env.GH_REPO}/actions/workflows/${WORKFLOWS[kind]}/dispatches`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${process.env.GH_DISPATCH_TOKEN}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
        body: JSON.stringify({
          ref: process.env.GH_DISPATCH_REF ?? 'main',
          inputs: { dry_run: String(opts.dryRun), limit: String(opts.limit ?? ''), segment: opts.segment ?? '' },
        }),
      },
    )
    return res.status === 204 ? { ok: true as const } : { ok: false as const, message: `GitHub said ${res.status}` }
  }
  ```
  The input names (`dry_run`, `limit`, `segment`) must match the `workflow_dispatch` inputs in Step 14.
- **Custom search queue:** form (segment, query, for example "dental chains in Dubai with 3+ branches"). Inserts into `custom_queries` with status `new`. The table below shows each query's status as the night run processes it.

### 15.6.9 `/inbox` (admin only)
- Paste a public post: URL, the post text (copied by hand), segment. Inserts into `inbox_posts` with status `new`.
- The engine never opens LinkedIn or X links; it works from the pasted text and searches the business on allowed sources (A.4).
- Table of posts with status (`new`, `researched`, `lead_created`, `rejected`) and a link to the created lead.

### 15.6.10 `/settings`
- `/settings` (all roles): full name, change password (uses `PasswordSchema`), log out of other sessions (`supabase.auth.signOut({ scope: 'others' })`). Shows the forced change-password banner when `?change_password=1`.
- `/settings/users` (admin): table of users (name, email, role, last sign in, status). Actions: **Create user**, **Change role**, **Reset password** (shows a new temporary password once), **Disable**.
- `/settings/suppression` (admin): table of `suppression` rows (phone, email, domain, reason, added by, date). Add and remove. Removing asks "Remove from do-not-contact?" in a dialog.

---

## 15.7 Role access matrix (enforcement summary)

| Check | Where it is enforced |
|---|---|
| Logged in | Middleware (`updateSession`) and every Server Action (`requireRole`) |
| Admin-only pages | `requireRole(['admin'])` at the top of the page and of every action |
| Caller cannot read money | `v_leads_caller` has no money column; column grants in Step 2; `v_leads_admin` returns nothing for non-admins |
| Caller cannot write money | Only admin actions write `deal_value_inr`, using the admin client after the role check |
| Viewer cannot write | RLS denies writes for `viewer`; UI hides edit controls |
| Service role key safety | Only in `import 'server-only'` files; never `NEXT_PUBLIC_`; never sent in props |

---

## 15.8 Performance, accessibility and mobile

### 15.8.1 Performance
- Select only the columns a page needs. Never `select('*')` on `pages.text` or other large columns.
- Lists are paginated on the server (50 rows). Today shows at most 100 rows with "Show more".
- Use `Promise.all` for independent queries on one page.
- Mark data pages `export const dynamic = 'force-dynamic'` (they are per-user).
- Indexes the app relies on (Step 2): `leads(stage)`, `leads(grade)`, `leads(due_at)`, `leads(segment_id)`, `activities(lead_id, at desc)`, `signals(business_id, observed_at desc)`, trigram on `businesses.norm_name`.

### 15.8.2 Accessibility
- Every input has a visible label. Errors are linked with `aria-describedby`.
- Focus ring visible on every control (indigo, 2px).
- Colour is never the only signal: stage badges always show the label text, overdue dates show the word "overdue".
- Toasts use an `aria-live` region (sonner does this).
- Pipeline board works with the keyboard (dnd-kit `KeyboardSensor`).
- Contrast: kit text colours on white pass WCAG AA; check stage badge pairs with the axe test (15.10.3).

### 15.8.3 Mobile
- Today and the Lead page must be fully usable on a phone (Aditya may send from his phone).
- Under 640px: tables become stacked cards (company, grade, stage, buttons), filters move into a Drawer, KPI tiles become a 2-column grid.
- On phones the **Open WhatsApp app** button is first and largest.
- Tap targets at least 40px high.
- Optional later: a web app manifest so the app can be added to the home screen.

---

## 15.9 Errors and logging
- `src/app/(app)/error.tsx`: calm message "Something went wrong on this page." with a **Try again** button (`reset()`), plus the error digest in `label-mono` for support.
- `not-found.tsx`: "This lead does not exist or you do not have access."
- Server Actions return `{ ok: false, message }` with plain words; never show raw database errors to users. Log the full error with `console.error` (Render keeps logs).
- Optional later: Sentry for error alerts.

---

## 15.10 Tests

### 15.10.1 Unit tests (vitest)
`web/vitest.config.ts` with the jsdom environment. Cover:
| Test | Checks |
|---|---|
| `lint.test.ts` | Same cases as the engine's lint in Step 12: word count, one question mark, no links, no dashes, no emojis, banned phrases |
| `whatsapp.test.ts` | `waLinks('+91 98110 12345', 'Hi, test?')` builds both links with digits only and the text encoded |
| `stages.test.ts` | Every DB stage from A.12.2 has a label and colours; unknown stage falls back to New |
| `password.test.ts` | Rejects short or simple passwords, accepts a valid one |
| `csv.test.ts` | Quotes, commas and new lines are escaped |
| `dates.test.ts` | UTC to IST formatting, start of the IST week |

Run: `pnpm vitest run`.

### 15.10.2 End-to-end tests (Playwright)
Run against the **dev** Supabase project only.
1. `scripts/seed-test-users.ts` (refuses to run when `APP_ENV=prod`): creates `admin@test.local` and `caller@test.local` with known passwords, their `profiles` rows, and 5 seeded leads (2 with stage `new`, 3 on the pipeline, 1 with `deal_value_inr = 150000`).
2. `playwright.config.ts`: `baseURL` `http://localhost:3000`, a global setup that logs in as each user and saves `storageState` files, projects for Desktop Chrome and iPhone 14.
3. Specs:
   | Spec | Steps and expectations |
   |---|---|
   | `login.spec.ts` | Wrong password shows the generic message. Right password lands on Today. Logged-out visit to `/leads` redirects to `/login?next=/leads`. |
   | `today.spec.ts` | Caller clicks **Mark sent** on a lead: it leaves the list, toast shows Undo. Database row has `stage = contacted` and `wa_at` set; an `activities` row with `type = sent` and `source = app` exists. Undo restores it. |
   | `lead.spec.ts` | Open a lead, change stage to Talking: the timeline shows the change; the Pipeline page shows the card in Talking. Edit the message with a dash: lint shows the problem; Save is blocked until fixed. |
   | `money.spec.ts` | As caller: the lead page has no "Deal value" text; `/engine` redirects to `/`; a direct query with the caller session `from('leads').select('deal_value_inr')` returns an error or no value; CSV export has no money column. As admin: deal value is visible and editable. |
   | `reset.spec.ts` | Request a reset: the same success message shows for a real and an unknown email. |
   | `mobile.spec.ts` | iPhone 14: Today renders cards, **Open WhatsApp app** is the first button, no horizontal scroll. |
4. Run: `pnpm playwright test`.

### 15.10.3 Accessibility check
In `today.spec.ts` and `lead.spec.ts`, run axe:
```ts
import AxeBuilder from '@axe-core/playwright'
const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
expect(results.violations).toEqual([])
```

### 15.10.4 CI
Add a `web` job to `.github/workflows/ci.yml` (Step 17): `pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm tsc --noEmit`, `pnpm vitest run`. Run Playwright only on pull requests to `main`, with dev secrets.

---

## 15.11 Deploy on Render

### 15.11.1 Standalone build helper
`web/scripts/copy-standalone.mjs` (Next's standalone output does not include static files by default):
```js
import { cpSync, existsSync } from 'node:fs'
cpSync('.next/static', '.next/standalone/.next/static', { recursive: true })
if (existsSync('public')) cpSync('public', '.next/standalone/public', { recursive: true })
console.log('standalone assets copied')
```
`web/package.json` scripts:
```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build && node scripts/copy-standalone.mjs",
    "start": "node .next/standalone/server.js",
    "lint": "next lint",
    "test": "vitest run",
    "e2e": "playwright test"
  }
}
```

### 15.11.2 `render.yaml` (repository root)
```yaml
services:
  - type: web
    name: nument-leads-web
    runtime: node
    region: singapore              # closest Render region to India
    plan: starter                  # "free" sleeps after 15 min idle; starter (about $7/month) stays awake
    rootDir: web
    buildCommand: corepack enable && pnpm install --frozen-lockfile && pnpm build
    startCommand: pnpm start
    healthCheckPath: /api/health
    autoDeploy: true
    buildFilter:
      paths:
        - web/**
    envVars:
      - key: NODE_VERSION
        value: "22"
      - key: HOSTNAME
        value: 0.0.0.0             # standalone server must listen on all interfaces
      - key: APP_ENV
        value: prod
      - key: NEXT_PUBLIC_SUPABASE_URL
        sync: false                # set in the dashboard; needed at BUILD time
      - key: NEXT_PUBLIC_SUPABASE_ANON_KEY
        sync: false
      - key: NEXT_PUBLIC_APP_URL
        value: https://leads.nument.in
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: GH_DISPATCH_TOKEN
        sync: false
      - key: GH_REPO
        sync: false
      - key: GH_DISPATCH_REF
        value: main
```
Render sets `PORT`; the standalone server reads it automatically.

### 15.11.3 First deploy
1. Push the repo to GitHub (Step 1).
2. Render dashboard: **New**, **Blueprint**, connect the GitHub account, pick the `nument-leads` repo. Render reads `render.yaml`.
3. Fill every `sync: false` value with the **prod** Supabase values and tokens.
4. Click **Apply**. Wait for the build. Open `https://nument-leads-web.onrender.com/api/health`: it returns `{"ok":true,"env":"prod",...}`.
5. Open `/login`, sign in as the founder (admin created in Step 2 seed on prod).
6. Every push to `main` that changes `web/**` redeploys automatically.

### 15.11.4 Custom domain `leads.nument.in`
1. Render service, **Settings**, **Custom Domains**, add `leads.nument.in`.
2. GoDaddy DNS for `nument.in`: add a **CNAME** record, name `leads`, value `nument-leads-web.onrender.com`, TTL 1 hour. Do not touch the existing records for the main website.
3. Wait for Render to show the domain as verified and the certificate as issued (minutes to an hour).
4. Update Supabase Auth Site URL and Redirect URLs (15.3.1), and `NEXT_PUBLIC_APP_URL`. Redeploy (public variables are build-time).

### 15.11.5 Free vs Starter
| | Free | Starter |
|---|---|---|
| Cost | $0 | about $7 a month (check render.com) |
| Sleeps | after 15 minutes idle | never |
| First load after sleep | 30 to 60 seconds | instant |
| Recommendation | fine for building and testing | use at go-live, the founder opens it every morning |

### 15.11.6 Things the web app must never do
- Scrape websites or call data sources. All data collection happens in the engine (GitHub Actions).
- Send WhatsApp messages. It only opens WhatsApp with the text ready.

---

## 15.12 Build order inside Step 15

| Day | Work | Check |
|---|---|---|
| 1 | 15.2 setup, clients, middleware, health route | `pnpm dev` runs; `/api/health` ok |
| 2 | 15.3 auth: login, logout, reset flow, roles helper | Founder logs in on dev |
| 3 | 15.4 design system, layout shell, sidebar by role | Shell looks like the kit, DEV badge shows |
| 4 to 5 | Today page with send list, WhatsApp buttons, actions, undo | Mark sent writes `wa_at` + activity |
| 6 to 7 | Leads list: filters, search, pagination, saved views, export | Filters update the URL; export works |
| 8 to 9 | Lead page: all sections, message editor with lint, timeline, feedback | Every section renders with seeded data |
| 10 | Deal and proposal upload (admin), users and suppression settings | Caller cannot see money |
| 11 | Pipeline board with drag and drop | Drag updates stage optimistically |
| 12 | Insights | Rates match a hand count on seeded data |
| 13 | Engine and Inbox pages, run triggers | Run night (dry run) starts a GitHub Action |
| 14 | Tests (unit, e2e, axe), mobile pass | All green |
| 15 | Render deploy, domain, prod smoke test | Founder signs in on `leads.nument.in` |

---

## 15.13 Names this step adds (to keep the contract in sync)
These are used by Step 15 and must exist in Step 2:
- Views: `v_today`, `v_leads_caller`, `v_leads_admin`, `v_followups_due`, `v_funnel`, `v_costs_daily` (columns in 15.5.1, `security_invoker = true` except where noted).
- Table `saved_views` (`id` uuid, `user_id` uuid, `name` text, `query` jsonb, `shared` bool default false, `created_at`).
- `leads` columns `skipped_until` (timestamptz) and `regen_requested_at` (timestamptz).
- Storage bucket `proposals` (private).
- Activity `type` values: `sent`, `followup_sent`, `stage_change`, `edit`, `note`, `skip`, `wrong_contact`, `feedback`, `proposal_upload`, `regen_request`, `undo`.
- Environment variables: `NEXT_PUBLIC_APP_URL`, `GH_REPO`, `GH_DISPATCH_REF`.
- `workflow_dispatch` inputs on `night.yml`, `morning.yml`, `sheet-sync.yml`: `dry_run`, `limit`, `segment`.
- Auth user metadata flag `must_change_password` (no table needed).

---

## 15.14 Pitfalls
| Pitfall | What happens | Fix |
|---|---|---|
| `cookies()` used without `await` | Build error or broken sessions in Next 15+ | Always `await cookies()` |
| Middleware file name | Next 16+ ignores `middleware.ts` | Rename to `proxy.ts` and export `proxy` if your version needs it |
| `NEXT_PUBLIC_*` set after the build | The browser still has the old values | Set them in Render before building; redeploy after changes |
| `window.open` after an `await` | Popup blocked, WhatsApp does not open | Open the link first, then call the action |
| Views without `security_invoker` | Views run as the owner and skip RLS, so callers could see everything | Step 2 creates views with `security_invoker = true` |
| Service role imported in a client file | Key leaks to the browser | `import 'server-only'` in every file that uses it |
| Using `getSession()` on the server | Session can be spoofed | Use `getUser()` (or `getClaims()`) |
| Supabase built-in email limits | Reset emails stop arriving | Add custom SMTP, or reset from `/settings/users` |
| Render free plan sleeping | First morning load takes up to a minute | Starter plan at go-live |
| Showing UTC times | Confusing dates | Always format with `Asia/Kolkata` |
| Long quotes and page text in lists | Slow pages | Only the lead page loads quotes; never load `pages.text` |

---

## 15.15 Done when
- [ ] `pnpm dev` runs the app locally against the dev Supabase project, and `/api/health` returns ok.
- [ ] Public sign-up is off in Supabase; the founder logs in with email and password; logged-out users are redirected to `/login`.
- [ ] An admin can create a user from `/settings/users`; the new user must change the temporary password on first login.
- [ ] Forgot password sends a link that opens `/reset-password/update` and sets a new password.
- [ ] The app uses Newsreader, Figtree and DM Mono, kit colours and spacing, with no floating cards or decorative pills.
- [ ] Today shows KPI tiles, the send list from `v_today`, and follow-ups due; **Open WhatsApp Web** opens WhatsApp Web with the message typed **and** marks the lead Contacted with `wa_at` and a `sent` activity; Undo works.
- [ ] Skip hides a lead for 7 days; Wrong contact sets the stage, adds the phone to suppression, and can be undone.
- [ ] Leads list filters by segment, country, city, grade, signal, stage and pitch mode; search works; saved views work; CSV export works and has no money column for callers.
- [ ] The Lead page shows header, contact card, why this lead with score breakdown and judge note, signals with evidence links, verified facts, website and tech check, message editor with lint and regenerate, follow-ups, timeline with sources, notes and feedback.
- [ ] Admin sees and edits deal value and uploads proposals to the private `proposals` bucket; caller and viewer never see money anywhere (page, export, direct query).
- [ ] Pipeline drag and drop changes stages with optimistic updates, on desktop, touch and keyboard.
- [ ] Insights shows the funnel, rates by segment, country, signal, pitch mode, angle and test group, lead quality, and (admin) costs against the ₹750 cap.
- [ ] Engine page toggles segments and sources, edits quotas and the daily cap, lists runs and source health, and **Run night (dry run)** starts the GitHub Action.
- [ ] Inbox accepts pasted posts; Settings manages profile, password, users, roles and suppression.
- [ ] Every change from the app appears in `activities` with `source = 'app'` and reaches the Google Sheet at the next sheet sync.
- [ ] Unit tests, Playwright tests (including caller cannot see money and mobile layout) and the axe check pass in CI.
- [ ] The app is live on Render (Starter plan at go-live) at `leads.nument.in` with a valid certificate, and the founder can sign in there.

---

# Step 16: Learning loop and reports

**Goal:** turn the stages the founder marks (in the app or the sheet) into numbers, use those numbers to adjust scoring every week, and give the founder one clear weekly report that says what to scale and what to cut.

**You need first:** Steps 2 (tables `leads`, `activities`, `feedback`, `scores`, `signals`, `costs`), 11 (scoring reads weights from `settings`), 13 (sheet edits land in `activities`), 15 (app edits land in `activities`).

**Files you create in this step:**
```
engine/src/nument_engine/learn/metrics.py     # funnel events + rates per cut
engine/src/nument_engine/learn/reweight.py    # weekly weight update (Beta-binomial, later logistic)
engine/src/nument_engine/learn/report.py      # weekly report (stored + optional email)
engine/tests/test_learn_metrics.py
engine/tests/test_learn_reweight.py
supabase/migrations/0007_learning.sql         # two small tables, see 16.4.1 and 16.6.1
```

## 16.1 Funnel events (what counts as what)

### 16.1.1 Stage order
Every stage gets a rank. A lead's **highest rank ever reached** decides which funnel events it counts for, even if it later moved to a closed stage. Example: a lead that went Contacted, then Talking, then Lost still counts as **contacted** and **replied**.

| Rank | Stages | Funnel event it unlocks |
|---|---|---|
| 0 | `new` | none |
| 1 | `contacted` | `contacted` |
| 2 | `talking` | `replied` |
| 3 | `discovery_booked`, `discovery_done` | `meeting` |
| 4 | `proposal_sent` | `proposal` |
| 5 | `won`, `retainer` | `won` |
| closed, no rank | `lost`, `not_now`, `not_a_fit`, `wrong_contact` | keep the highest rank reached before closing |

Special cases:
1. `wrong_contact` never counts as `contacted` for reply-rate maths (we never reached the business). It counts only in the **data quality** section of the report.
2. A lead with `wa_at` set but stage still `new` counts as `contacted` (the founder sent but forgot to change the stage).
3. `not_a_fit` after `talking` counts as `replied` (they replied, then turned out wrong). It also adds one negative label for scoring (16.5).

### 16.1.2 Where the history comes from
- Every stage change writes one `activities` row with `type = 'stage_change'` and `payload = {"from": "<stage>", "to": "<stage>"}`. The app (Step 15) and the sheet pull (Step 13) both write these, with `source` = `app` or `sheet`.
- The highest rank reached = max over all `stage_change` rows for the lead, plus the current `leads.stage`.

### 16.1.3 Cohorts and attribution windows
- A lead belongs to the **ISO week of its first contact** (`wa_at`, or the first `stage_change` to `contacted`).
- Events count only inside these windows after first contact:

| Event | Window | Why |
|---|---|---|
| `replied` | 21 days | Late replies are rare and usually come from follow-ups |
| `meeting` | 45 days | Discovery calls get rescheduled |
| `proposal` | 60 days | |
| `won` | 120 days | Clinics and real estate decide slowly |

- A cohort is **mature** for an event once its window has passed. Rates are reported for mature cohorts first, with immature cohorts shown separately and labelled "still open".

### 16.1.4 SQL for the funnel base (put in `0007_learning.sql` as a view)
```sql
create or replace view v_lead_funnel as
with stage_rank(stage, rnk) as (
  values ('new',0),('contacted',1),('talking',2),('discovery_booked',3),('discovery_done',3),
         ('proposal_sent',4),('won',5),('retainer',5),
         ('lost',null),('not_now',null),('not_a_fit',null),('wrong_contact',null)
),
hist as (
  select a.lead_id, max(sr.rnk) as max_rank_hist,
         min(a.at) filter (where a.payload->>'to' = 'contacted') as first_contacted_at
  from activities a
  join stage_rank sr on sr.stage = a.payload->>'to'
  where a.type = 'stage_change'
  group by a.lead_id
)
select l.id as lead_id, l.segment_id, b.country, l.pitch_mode, l.angle, l.test_group, l.grade,
       coalesce(l.wa_at, h.first_contacted_at) as contacted_at,
       greatest(coalesce(h.max_rank_hist,0), coalesce(sr.rnk,0),
                case when l.wa_at is not null then 1 else 0 end) as max_rank,
       (l.stage = 'wrong_contact') as is_wrong_contact,
       l.stage
from leads l
join businesses b on b.id = l.business_id
left join hist h on h.lead_id = l.id
left join stage_rank sr on sr.stage = l.stage;
```

## 16.2 `learn/metrics.py`

### 16.2.1 What it computes
For every **cut** (a way of grouping leads) it returns counts and rates:

| Cut | Grouping key |
|---|---|
| Segment | `segment_id` |
| Country | `businesses.country` |
| Signal type | each active signal type on the lead at the time it was created (a lead with two signals counts in both rows) |
| Pitch mode | `pitch_mode` |
| Angle | `angle` |
| Test group | `test_group` |
| Grade | `grade` |
| Reach type | the `phone_type` of the contact used (`mobile`, `landline`, email only, form only) |

Counts per row: `contacted`, `replied`, `meetings`, `proposals`, `won`, `wrong_contact`.
Rates per row: `reply_rate = replied / contacted`, `meeting_rate = meetings / contacted`, `proposal_per_20 = proposals / contacted * 20`, `win_rate = won / contacted`.
Also: a 90% credible interval for each rate from Beta(1 + successes, 1 + failures), so small samples are not over-read.

### 16.2.2 Signal attribution
- When a lead is created (Step 12), store the list of active signal types in `leads`? No: keep the contract. Instead read them from `scores.reasons`, which Step 11 fills with `{"signals": [{"type": "...", "points": ...}, ...]}`.
- If `scores.reasons` lacks the list (older leads), fall back to `signals` rows for the business with `observed_at <= leads.created_at < expires_at`.

### 16.2.3 Code outline
```python
# engine/src/nument_engine/learn/metrics.py
from dataclasses import dataclass
from scipy.stats import beta  # optional; fallback below if scipy is not installed

CUTS = ("segment_id", "country", "signal_type", "pitch_mode", "angle", "test_group", "grade", "reach_type")
WINDOWS_DAYS = {"replied": 21, "meeting": 45, "proposal": 60, "won": 120}

@dataclass
class CutRow:
    cut: str
    key: str
    contacted: int
    replied: int
    meetings: int
    proposals: int
    won: int
    wrong_contact: int
    reply_rate: float
    meeting_rate: float
    proposal_per_20: float
    meeting_ci90: tuple[float, float]
    mature: bool

def load_funnel(conn, since_days: int = 120) -> list[dict]:
    """Rows from v_lead_funnel joined with signal types and reach type, contacted in the last N days."""

def rates_by_cut(rows: list[dict], cut: str, today) -> list[CutRow]:
    """Group rows by the cut. Only count an event if it happened inside its window.
    'mature' is True when every lead in the row is older than the meeting window (45 days)."""

def credible_interval(successes: int, trials: int, mass: float = 0.90) -> tuple[float, float]:
    a, b = 1 + successes, 1 + max(trials - successes, 0)
    return float(beta.ppf((1 - mass) / 2, a, b)), float(beta.ppf(1 - (1 - mass) / 2, a, b))
```
Dependency note: add `scipy` (and later `scikit-learn`, see 16.4.4) to `engine/pyproject.toml` in Step 1. If you prefer no scipy, compute the interval with the normal approximation and mark it "approximate".

### 16.2.4 Decision labels per row
Apply these rules to every row of the **test group** cut (and show them for segment and signal type too):

| Label | Rule |
|---|---|
| `scale` | `contacted >= 50` and `meeting_rate >= 0.08` and `proposal_per_20 >= 1` |
| `keep` | `contacted >= 50` and `0.03 <= meeting_rate < 0.08` |
| `cut` | `contacted >= 100` and `meeting_rate < 0.03` |
| `watch` | `contacted < 50`, or `contacted` between 50 and 99 with `meeting_rate < 0.03` |
| `early_signal` | before meetings mature: `contacted >= 30` and `reply_rate >= 0.10` (green) or `< 0.03` (red) |

The engine never turns a segment or test group off by itself. It recommends; the founder decides in the app (Step 15 engine page) by toggling `settings.segments_enabled` or changing quotas.

## 16.3 What "weights" are
Scoring (Step 11) uses three groups of numbers that learning may adjust:
1. **Signal points**: the default points per signal type from A.12.3, per segment.
2. **Can-pay proxy points**: the points for each can-pay proxy in the segment YAML (Step 3).
3. **Pitch mode share**: how many fit-only leads are allowed per day (default 10%).

All three live in one JSON document in `settings` under the key `score_weights`:
```json
{
  "version": 7,
  "updated_at": "2026-12-14T02:10:00+05:30",
  "signal_points": {
    "clinics-in": {"hiring_frontdesk": 8.0, "review_pain": 6.6, "public_ask": 10.0, "no_booking": 3.0},
    "realestate-in": {"hiring_frontdesk": 8.8, "review_pain": 6.0}
  },
  "can_pay_points": {
    "clinics-in": {"branches_2plus": 8.0, "reviews_100plus": 6.0, "pays_for_software": 4.0}
  },
  "fit_only_share": 0.10
}
```
Missing entries fall back to the defaults in A.12.3 and the segment YAML. Step 11 must read `score_weights` first, then defaults.

## 16.4 `learn/reweight.py`: weekly re-weighting

### 16.4.1 Version history table (`0007_learning.sql`)
```sql
create table if not exists weight_versions (
  id bigserial primary key,
  version int not null unique,
  weights jsonb not null,
  method text not null check (method in ('defaults','beta_binomial','logistic','manual')),
  reason text,
  diff jsonb,                       -- what changed vs previous version
  created_by text not null default 'engine',
  created_at timestamptz not null default now()
);
```
Every change writes a new row and then updates `settings.score_weights`. Rolling back = copying an older version's `weights` into `settings` (button on the app engine page, admin only).

### 16.4.2 Beta-binomial update (default method, from week 3 onwards)
For each segment and each signal type with enough data:
1. Success = `meeting` (rank 3 or more) inside its window. Until a segment has 15 or more meetings in total, use `replied` (rank 2) as the success event and mark the update "early, based on replies".
2. Prior: Beta(1, 19), a 5% base rate. This keeps small samples close to the default.
3. For the signal type: `p_sig = (successes + 1) / (contacted + 20)`.
4. For the whole segment: `p_seg = (successes_all + 1) / (contacted_all + 20)`.
5. Raw multiplier: `m = p_sig / p_seg`.
6. Clamp the weekly change: `m_week = min(max(m, 0.8), 1.2)` (at most 20% up or down per week).
7. New points: `new = old * m_week`, then clamp to `[0.5 * default, 2.0 * default]` so no signal can drift far from common sense.
8. Only update a signal type if it has **30 or more contacted leads** in mature cohorts. Otherwise keep it unchanged.
9. Round to one decimal.

The same procedure runs for can-pay proxies (success = `meeting`), with the same clamps.

```python
# engine/src/nument_engine/learn/reweight.py
PRIOR_A, PRIOR_B = 1, 19
MIN_CONTACTED = 30
WEEKLY_CLAMP = (0.8, 1.2)
ABS_CLAMP = (0.5, 2.0)

def beta_mean(successes: int, trials: int) -> float:
    return (successes + PRIOR_A) / (trials + PRIOR_A + PRIOR_B)

def update_points(old: float, default: float, s_sig: int, n_sig: int, s_seg: int, n_seg: int) -> tuple[float, str]:
    if n_sig < MIN_CONTACTED:
        return old, "not enough data"
    m = beta_mean(s_sig, n_sig) / beta_mean(s_seg, n_seg)
    m = min(max(m, WEEKLY_CLAMP[0]), WEEKLY_CLAMP[1])
    new = min(max(old * m, ABS_CLAMP[0] * default), ABS_CLAMP[1] * default)
    return round(new, 1), f"x{m:.2f}"

def run_reweight(conn, dry_run: bool = False) -> dict:
    """1. load current weights (settings.score_weights or defaults)
       2. compute successes/trials per segment x signal type and per can-pay proxy (mature cohorts only)
       3. propose new weights with update_points
       4. write weight_versions row + update settings (unless dry_run)
       5. return the diff for the weekly report"""
```

### 16.4.3 Safety rules for re-weighting
- Re-weighting runs only in the weekly job (Monday), never nightly.
- If the eval gate (Step 17.4) fails with the proposed weights on the golden set, the update is **not applied**. The report says "weights proposal rejected by eval".
- A founder can freeze weights (`settings.score_weights_frozen = true`, a new settings key) from the app.
- Every applied change appears in the weekly report under "What the engine changed".

### 16.4.4 Logistic regression (only after 200 or more mature outcomes)
When a segment has 200 or more contacted leads with mature `replied` outcomes:
1. Features per lead: decayed points per signal type, each can-pay proxy (0 or 1), reach type (one-hot), pitch mode (one-hot), grade, country (one-hot), days from signal to first contact.
2. Target: `replied` within 21 days (later, once there are 200 meetings, switch to `meeting`).
3. Model: L2-regularised logistic regression (`scikit-learn` `LogisticRegression(C=0.5, class_weight='balanced')`), 5-fold cross-validation.
4. Accept the model only if its cross-validated AUC is at least 0.62 and beats the current points-based score's AUC on the same folds by 0.02 or more.
5. If accepted, convert coefficients into points (scale so the median A lead keeps roughly the same total) and save as a new `weight_versions` row with `method = 'logistic'`. The same weekly clamps and absolute clamps apply.
6. Store the model card (features, AUC, sample size, date) in the weekly report.

## 16.5 Feedback thumbs as labels
- The app (Step 15) lets the founder or caller give each lead a thumb up (`rating = 1`) or down (`rating = -1`) with a reason.
- Reasons (fixed list, multi-select in the app): `wrong_segment`, `too_small`, `too_big_or_corporate`, `agency_or_vendor`, `no_real_need`, `cannot_reach`, `already_has_solution`, `bad_message`, `great_lead`, `other`.
- Uses:
  1. **Weekly report**: top 5 reasons for thumbs down, per segment.
  2. **Golden set growth**: any thumbed lead can be promoted into `golden_labels` with one click (good for +1, bad for -1).
  3. **Exclusion learning**: if `agency_or_vendor` or `too_big_or_corporate` appears 3 or more times for the same name pattern or domain, the report suggests adding it to `engine/config/exclusions.yaml`.
  4. **Prompt fixes**: `bad_message` reasons are listed with the message text so the founder can see patterns. Changes to prompts go through the eval gate (Step 17).

## 16.6 `learn/report.py`: the weekly report

### 16.6.1 Storage table (`0007_learning.sql`)
```sql
create table if not exists reports (
  id bigserial primary key,
  kind text not null check (kind in ('weekly','audit','eval','monthly_cost')),
  period_start date,
  period_end date,
  content jsonb not null,           -- all numbers, for the app to render
  markdown text not null,           -- the same report as readable text
  created_at timestamptz not null default now()
);
create index if not exists reports_kind_created on reports(kind, created_at desc);
```
RLS (add to Step 2 policies): admin can read all; caller can read `weekly` but the money fields are removed from `content` before saving the caller version (store two rows: `content` for admin, and `content->'caller'` stripped of money, or render the caller view server-side without money).

### 16.6.2 Report sections (in this order)
1. **Headline** (3 lines): leads added this week, contacted, replies, meetings, proposals, won, money won (admin only).
2. **Funnel by segment and country**: table with counts, rates, 90% intervals, and the decision label (`scale`, `keep`, `cut`, `watch`).
3. **By signal type**: which signals produce replies and meetings.
4. **By pitch mode and angle**: stated need vs visible pain vs fit only. Shows whether signals matter at all (fit-only is the control).
5. **Test groups to scale or cut**: a short list with one line each: "Scale `clinics-ae:visible_pain:missed_calls`: 11% meetings from 64 contacted."
6. **Lead quality**: wrong contact rate, share with own phone, median signal age at first contact, thumbs down reasons, verified facts share.
7. **Cost**: spend this week, average per day vs the ₹750 cap, cost per researched business, per good lead, per meeting, per won client (admin only).
8. **Engine health**: runs ok vs failed, sources blocked, AI batch delays, sheet sync conflicts.
9. **What the engine changed**: weight changes (old to new, why), proposals rejected by eval.
10. **Last eval and audit**: golden set scores, audit agreement (Step 17).
11. **Suggested actions** (max 5 bullets, plain words).

### 16.6.3 Delivery
- **In-app**: the weekly report appears on the app's Insights area (Step 15 route `/insights`, tab "Weekly report"), newest first, with history.
- **Optional email**: if `ALERT_EMAIL` is set and an email provider key is configured, send the markdown version on Monday at about 08:00 IST. Use a transactional email API with a free tier (new optional variable `RESEND_API_KEY`), or skip email entirely. Never put money numbers in the caller's email.
- **GitHub job summary**: the weekly workflow (Step 14) also writes the markdown into the run summary, so it is visible even if the app is down.

### 16.6.4 Code outline
```python
# engine/src/nument_engine/learn/report.py
def build_weekly(conn, week_start, week_end) -> tuple[dict, str]:
    """Collect sections 16.6.2 into a dict (content) and render markdown with jinja2.
    Uses metrics.rates_by_cut for every cut, reweight.run_reweight(dry_run=False) diff,
    costs table aggregates, runs and source_health, last reports of kind 'eval' and 'audit'."""

def save_and_send(conn, content: dict, md: str, settings) -> int:
    """Insert into reports (kind='weekly'); email if ALERT_EMAIL + RESEND_API_KEY; return report id."""
```

## 16.7 Done when
- [ ] `v_lead_funnel`, `weight_versions` and `reports` exist in dev and prod (migration `0007_learning.sql`).
- [ ] `nlead learn --dry-run` prints rates for every cut on test data without errors.
- [ ] Unit tests cover: stage rank logic (including `wrong_contact` and closed stages), windows, Beta-binomial maths, both clamps, the 30-lead minimum.
- [ ] `nlead report weekly` writes a `reports` row and the app shows it under Insights.
- [ ] A weight change creates a `weight_versions` row and can be rolled back from the app.
- [ ] A proposed weight change that fails the eval gate is not applied, and the report says so.
- [ ] Thumbs up and down with reasons appear in the report and can be promoted to the golden set.

---

---

# Step 17: Quality: tests, golden set, evals, CI

**Goal:** make quality measurable so that no prompt, model, weight or rule change can quietly make leads worse.

**You need first:** Steps 1 (test tooling), 2 (schema), 4 (AI router with mock mode), 9 to 12 (the pipeline steps being tested), 15 (golden labelling in the app).

## 17.1 Test layers

| Layer | Tool | Runs where | Talks to the internet? | Cost |
|---|---|---|---|---|
| Unit | pytest | every push (CI) | no | ₹0 |
| Database | pytest + Postgres service container | every push (CI) | no | ₹0 |
| Integration (live, small) | pytest `-m live` | manually, and nightly smoke on dev | yes (tiny limits) | under ₹5 a run |
| Golden eval | `nlead eval` | CI gate when quality-relevant files change, and weekly | AI only, cached pages | about ₹60 for 20 items |
| Web end to end | Playwright | every push touching `web/` | Supabase dev only | ₹0 |
| RLS | SQL test file | every push touching `supabase/` | no | ₹0 |

## 17.2 Unit and integration tests per module

### 17.2.1 Fixtures
```
engine/tests/fixtures/
├── http/                     # saved responses: robots.txt variants, 403 challenge pages, 429
├── overture/sample_pune.parquet
├── places/search_ids.json, details_enterprise.json, details_reviews.json
├── art_registry/list_page.html
├── practo/clinic_profile.html
├── apna/sitemap_index.xml, job_sitemap.xml, job_page.html
├── gdelt/artlist.json
├── sites/<business>/home.html, about.html, contact.html, careers.html   # 10 real-shaped sites
├── llm/extract_facts_ok.json, extract_facts_bad_quote.json, judge.json, message.json
└── sheet/pipeline_values.json, snapshot_master.json
```
Rules for fixtures:
1. Save real pages once (with permission of robots.txt), strip personal data that is not business contact data, and commit them.
2. Never call live services from unit tests. Use `respx` to mock httpx and a `FakeLLM` provider in the router (Step 4 must expose a `mock` provider).
3. Each fixture has a one-line comment in `fixtures/README.md` saying where it came from and when.

### 17.2.2 What to test, module by module

| Module | Must-have tests |
|---|---|
| `http.py` | never-fetch hosts raise before any request; robots disallow skips and records; per-host rate limit spacing; 403 with challenge markers raises `SourceBlocked` and sets `blocked_until`; 429 backs off and does not rotate anything; no proxy is ever configured (assert client proxies are empty) |
| `segments.py` | every YAML in `engine/segments/` validates; bad YAML gives a clear error naming the field; unknown signal types rejected |
| `budget.py` | spend below alert passes; at 80% sets alert flag; at cap blocks `optional` then `important` tasks but allows `essential` until 100%; INR conversion uses `fx_inr_per_usd` |
| `llm/router.py` | task routes to the model in `tasks.yaml`; JSON schema violation triggers one retry then fails cleanly; cost row written per call with tokens; batch mode builds the right request file |
| `sources/*` | each parser on its fixture returns the expected records; empty or changed pages raise a parse warning, not a crash; grey sources respect their slower rate |
| `pipeline/resolve.py` | same domain merges; same phone merges; same `place_id` merges; name similarity above threshold and close distance merges; similar names far apart do not merge; chain with many branches becomes one business with `branches_count` |
| `pipeline/signals.py` | decay buckets (30%, 60%, 100% of window); `dedupe_key` prevents duplicates; `expires_at` set from A.12.3 |
| `pipeline/prefilter.py` | exclusions from `exclusions.yaml` drop matches; suppression drops; 90-day cooldown; daily quota and fit-only 10% cap respected |
| `research/pages.py` | picks home, about, team, contact, careers, locations, pricing in priority order; max 8 pages; skips social hosts |
| `research/techstack.py` | detects WhatsApp links, chat widgets, booking widgets, CMS from fixtures |
| `pipeline/verify.py` | exact quote passes; whitespace and case differences pass; paraphrase fails; partial match above threshold passes; phone type detection (India mobile, landline, toll free; UAE mobile) |
| `pipeline/score.py` | golden numbers: 6 hand-built businesses with known expected `total` and `grade`; reach multiplier; fit gate under 2 means no lead |
| `pipeline/judge.py` | judge cannot move a grade by more than one step; judge output without fact ids is rejected |
| `pipeline/message.py` | lint catches links, emojis, dashes, banned phrases, more than one question, length outside 30 to 60 words; similarity check rejects near-duplicates within a day |
| `sheet/push.py`, `sheet/pull.py` | snapshot comparison finds only real edits; conflict rule (latest timestamp wins) logs an activity; unknown stage text is tolerated; nothing is written if the build fails half way |
| `learn/*` | see Step 16.7 |

### 17.2.3 Database tests
- CI starts a `postgres:16` service container, creates a stub `auth` schema with a `users` table and an `auth.uid()` function, then applies every file in `supabase/migrations/` in order.
- Tests check: every table in A.12.1 exists; triggers set `updated_at`; one open lead per business is enforced; views return rows on seed data.

```sql
-- engine/tests/sql/auth_stub.sql (CI only, never applied to Supabase)
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as
$$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create role authenticated; create role anon; create role service_role;
```

### 17.2.4 RLS tests (`supabase/tests/rls_test.sql`)
Run as each role by setting `request.jwt.claim.sub` and `role`:
1. `caller` cannot select `deal_value_inr` (column privilege or view, as Step 2 defines) and cannot read `costs`.
2. `caller` can update `stage`, dates and `notes` on leads, and nothing else.
3. `viewer` can read but not update.
4. `anon` can read nothing.
5. `admin` can do everything.

### 17.2.5 Live integration tests (`pytest -m live`)
- Each source adapter fetches at most 2 items from the real source on the dev environment.
- The AI router makes one tiny call per provider (under ₹1).
- Never run live tests against prod data.

### 17.2.6 Coverage targets
| Area | Target |
|---|---|
| Pure logic: `score`, `verify`, `resolve`, `prefilter`, message lint, `learn`, `budget` | 85% lines |
| Source parsers | 75% lines |
| Whole engine package | 65% lines |
| Web app utils and server actions | 60% lines |
Coverage is measured with `pytest --cov` and reported in CI. A drop of more than 5 points on a pull request fails CI.

## 17.3 The golden set

### 17.3.1 What it is
100 real businesses labelled by the founder as **good** or **bad** leads, spread across wave 1:

| Segment | Count |
|---|---|
| `clinics-in` | 25 |
| `realestate-in` | 15 |
| `education-in` | 15 |
| `clinics-ae` | 15 |
| `realestate-ae` | 15 |
| `education-ae` | 15 |

Aim for about 50 good and 50 bad, so the set can measure both precision and the ability to reject.

### 17.3.2 How to build it
1. After the first two nights on dev (Step 21.2), pick 100 businesses: 60 that the engine graded A or B, 40 that it graded C or D, across the segments above.
2. The founder labels them in the app: **Golden** view (admin only; Step 15 adds a filter "Golden candidates" on the leads list and a label control on the lead page). Each label is `good` or `bad` plus the reasons from 16.5. Time needed: about 2 hours.
3. Labels are stored in `golden_labels`. Export them to the repo with `nlead eval --export-golden`, which writes `engine/evals/golden/labels.jsonl` (business id, segment, label, reasons, date). The repo copy is what CI uses.
4. Freeze page snapshots for the golden businesses: copy their `pages` rows into `engine/evals/golden/pages/<business_id>.json`. This makes evals repeatable and cheap (no re-crawling in CI).

### 17.3.3 Hand-checked facts (30 businesses)
For 30 of the 100 (5 per segment), the builder checks facts by hand against the business's own pages and writes them to `engine/evals/golden/facts_truth.yaml`:
```yaml
- business_id: "6f1c..."
  segment: clinics-in
  checked_by: builder
  checked_at: 2026-12-01
  facts:
    decision_maker: {name: "Dr. Asha Rao", role: "Founder"}
    phones:
      - {e164: "+919800000123", type: mobile}
    branches_count: 12
    staff_count_min: 30
    booking_method: "phone and WhatsApp"   # one of: online_widget, phone, whatsapp, form, none
    whatsapp_present: true
    chat_widget: false
    has_in_house_tech: "no"                # yes, no, unknown
    is_agency_or_vendor: false
    services_include: ["ultrasound", "radiology"]
```
Only fields that the extraction schema (Step 9) produces are checked. A missing truth value means "not checked", not "false".

### 17.3.4 Keeping it fresh
- Add 10 new labels a month from thumbed leads (16.5).
- Re-check hand facts for 5 businesses a quarter (websites change).
- When a new segment launches, add 20 labels before it gets a real quota (Step 23).

## 17.4 Eval harness: `engine/evals/run_eval.py` (`nlead eval`)

### 17.4.1 What it runs
For each golden business (or a subset):
1. Load frozen pages from `engine/evals/golden/pages/`.
2. Run `extract_facts` (synchronous calls, not batch, so CI does not wait), then `verify`, `score`, `judge`, `write_message`, `check_message`, exactly as production does, using the **proposed** prompts, `tasks.yaml`, segment files and weights from the working tree.
3. Write nothing to the production tables. Results go to a temporary schema or to memory, and a summary row goes to `reports` with `kind = 'eval'` (on dev).

### 17.4.2 Metrics and thresholds
| Metric | Definition | Threshold (full set) | Threshold (20-item CI subset) |
|---|---|---|---|
| Fact precision | verified facts that match `facts_truth.yaml` / verified facts checked | 95% or more | 95% or more |
| Field recall | truth fields that the extraction found (verified) / truth fields | 80% or more | 75% or more |
| Phone accuracy | businesses whose top contact phone equals the truth phone / businesses with a truth phone | 95% or more | 90% or more |
| Grade precision at 50 | of the 50 highest-scored golden businesses, share labelled `good` | 80% or more | precision at 10: 70% or more |
| Bad rejection | of businesses labelled `bad`, share graded C or D | 70% or more | 60% or more |
| Message lint pass | messages that pass lint on the first attempt | 98% or more | 95% or more |
| Critic score | average `check_message` score (0 to 10) | 8.5 or more | 8.0 or more |
| Unverified claims in messages | message sentences with a specific claim not linked to a verified fact | 0 | 0 |

The harness prints a table and exits with code 1 if any threshold fails.

### 17.4.3 Subset selection
- `nlead eval --subset 20` picks a fixed, stratified 20 (seed 42): 4 from `clinics-in`, 3 from each other wave-1 segment, half good and half bad, always including at least 6 of the 30 hand-checked businesses.
- The subset list is stored in `engine/evals/golden/subset20.txt` so CI is repeatable.

### 17.4.4 Cost guard
- An eval run uses the same budget guard (Step 19). The CI subset costs about ₹60. The full set costs about ₹300.
- If today's spend plus the eval estimate would pass the cap, the eval is postponed and CI shows "eval skipped: budget", which blocks merging until it runs.

## 17.5 CI gate (`.github/workflows/ci.yml`)

### 17.5.1 Jobs
| Job | Runs when | Steps |
|---|---|---|
| `lint` | every push and pull request | ruff, mypy (engine); eslint, typecheck (web) |
| `unit` | every push and pull request | pytest (unit + database tests with the Postgres service container), coverage report |
| `rls` | changes under `supabase/` | apply migrations to the container, run `supabase/tests/rls_test.sql` |
| `web-e2e` | changes under `web/` | build, Playwright against Supabase dev with a test user |
| `eval-gate` | changes to `engine/prompts/**`, `engine/config/tasks.yaml`, `engine/config/prices.yaml` (model ids only), `engine/segments/**`, `engine/config/exclusions.yaml`, `engine/src/nument_engine/pipeline/{extract,verify,score,judge,message}.py` | `nlead eval --subset 20` on dev, fail on any threshold |

### 17.5.2 The eval-gate job (excerpt)
```yaml
  eval-gate:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: changed
        with:
          filters: |
            quality:
              - 'engine/prompts/**'
              - 'engine/config/tasks.yaml'
              - 'engine/config/exclusions.yaml'
              - 'engine/segments/**'
              - 'engine/src/nument_engine/pipeline/extract.py'
              - 'engine/src/nument_engine/pipeline/verify.py'
              - 'engine/src/nument_engine/pipeline/score.py'
              - 'engine/src/nument_engine/pipeline/judge.py'
              - 'engine/src/nument_engine/pipeline/message.py'
      - if: steps.changed.outputs.quality == 'true'
        uses: astral-sh/setup-uv@v6
      - if: steps.changed.outputs.quality == 'true'
        working-directory: engine
        env:
          APP_ENV: dev
          DATABASE_URL: ${{ secrets.DEV_DATABASE_URL }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          uv sync --frozen
          uv run nlead eval --subset 20 --env dev
```
Pin third-party actions to a commit SHA when you build (Step 18.6). `DEV_DATABASE_URL` is a CI secret holding the dev project's pooler URL (a dev-only copy of `DATABASE_URL`).

### 17.5.3 Branch protection
- `main` requires: `lint`, `unit`, and `eval-gate` (when triggered) to pass, and one approval (the founder or the builder).
- No direct pushes to `main` once Step 21 is done.

## 17.6 Weekly audit (`nlead audit`)

### 17.6.1 What it does (every Monday, in the weekly workflow)
1. Pick 20 leads created in the last 7 days, stratified by segment (at least 2 per enabled segment), including at least 4 grade A.
2. For each: re-fetch the business's key pages live (respecting all Step 18 rules), re-run `verify` on the stored facts against the fresh pages, and re-run `judge_lead` with the top model in a stricter **audit mode** (`weekly_audit` prompt, Appendix A.10).
3. Record per lead: grade agreement (same grade, one step off, two or more off), facts that no longer verify, phone still on the page, message claims still true.
4. Pick 5 of the 20 at random and put them in the founder's **Audit** queue in the app (a filter on the leads list: "Audit this week"), where he marks each "correct" or "wrong" with a reason.

### 17.6.2 Targets
| Measure | Target | If missed |
|---|---|---|
| Grade agreement (same or one step) | 85% or more | Open a task: check prompts and weights; run a full eval |
| Facts still verifying after 7 days | 95% or more | Shorten the re-research interval for that segment |
| Phones still on the page | 95% or more | Check verify step and source of phones |
| Founder marks "correct" | 4 of 5 or more | Read the reasons, fix the cause, add the 5 to the golden set |

### 17.6.3 Storage
The audit result is saved as `reports` with `kind = 'audit'` and summarised in the weekly report (16.6.2, section 10).

## 17.7 Done when
- [ ] All unit, database and RLS tests pass in CI, with the coverage targets in 17.2.6.
- [ ] `engine/evals/golden/labels.jsonl` has 100 labels; `facts_truth.yaml` has 30 businesses; frozen pages exist for all 100.
- [ ] `nlead eval` on the full set meets every threshold in 17.4.2 on dev.
- [ ] A pull request that changes a prompt runs `eval-gate` automatically and is blocked when a threshold fails (prove it once with a deliberately bad prompt on a test branch).
- [ ] `nlead audit` produces a `reports` row with `kind = 'audit'`, and 5 leads appear in the founder's Audit queue in the app.
- [ ] Branch protection is on for `main`.

---

---

# Step 18: Compliance, safety and security

**Goal:** make the rules in A.4 impossible to break by accident, keep personal data to the minimum, respect opt-outs forever, and keep keys and data safe.

**You need first:** Step 1 (`http.py` exists), Step 2 (tables `suppression`, `source_health`, `settings`), Step 5 (adapters use `http.py`).

## 18.1 Rules enforced in code (`engine/src/nument_engine/http.py`)

Every network request from the engine goes through one function, `polite_get` (and `polite_post` for official APIs). No adapter may create its own `httpx.Client` for scraping. Code review rejects any that does.

### 18.1.1 Never-fetch hosts
```python
NEVER_FETCH = {
    "linkedin.com", "x.com", "twitter.com", "instagram.com",
    "facebook.com", "fb.com", "threads.net", "tiktok.com",
    "web.whatsapp.com", "wa.me", "api.whatsapp.com",          # we build links to these, never fetch them
    "truecaller.com", "justdial.com",                           # broker-style or blocked sources
}

def host_blocked(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in NEVER_FETCH)
```
- `polite_get` raises `NeverFetch` before opening a socket if `host_blocked(url)` is true.
- Facebook (including the Meta Ad Library) is never fetched. Ads are checked by hand and entered in the app as the `ads_running` signal.
- Search-engine snippets that mention these hosts are allowed (A.4.1): grounded search returns text and links, and we store the link as evidence but never open it.

### 18.1.2 robots.txt
1. Fetch `/robots.txt` once per host per 24 hours (cache in memory and in a small cache table or file).
2. Check our User-Agent product token (`NumentLeadBot`) first, then `*`.
3. Disallowed path: skip the URL, record `pages.robots_allowed = false` if it was a page, and count it in `source_health`.
4. `robots.txt` returns 401 or 403: treat the whole host as disallowed. 404: treat as allowed. Timeout: treat as unknown and skip this run.
5. **Grey sources** (approved by the founder on 12 Nov 2026, A.4.1): a source marked `grey: true` in its adapter may fetch pages whose site terms ban robots, but it still obeys `robots.txt` path rules where they exist, runs at the slower grey rate, and stops when blocked. Today the grey sources are Apna job pages and, if ever enabled, the Google Maps scraper (not used in the Balanced tier).

### 18.1.3 Rate limits
| Source kind | Minimum gap per host | Daily cap | Concurrency |
|---|---|---|---|
| Official APIs (Places, Gemini, OpenAI, GDELT) | their documented limits | from A.10.2 | per API docs |
| Business websites (research) | 2 seconds | 8 pages per business per night | 6 hosts in parallel |
| Registries (ART, RERA, others) | 3 seconds | 500 pages per night | 1 |
| Practo profile pages | 5 seconds | 300 pages per night | 1 |
| Grey sources (Apna) | 6 seconds | 300 pages per night | 1 |

### 18.1.4 Honest identity
- Always send `User-Agent: NumentLeadBot/1.0 (+https://nument.in)` (env `USER_AGENT`).
- Never send a browser User-Agent to look like a person, never rotate User-Agents, never spoof headers.
- Playwright (for JavaScript pages) also sets the same User-Agent string.

### 18.1.5 Stop when blocked
```python
CHALLENGE_MARKERS = ("just a moment", "cf-chl", "captcha", "access denied", "are you a robot",
                     "unusual traffic", "verify you are human", "request blocked")

def looks_blocked(status: int, body: str) -> bool:
    if status in (401, 403, 429, 503):
        return True
    b = body[:5000].lower()
    return any(m in b for m in CHALLENGE_MARKERS)
```
- On a block: raise `SourceBlocked`; set `source_health.blocked_until = now() + 7 days` for that source (or that host for business websites); stop all further requests to it in this run.
- 429 from an official API: back off with exponential delay (tenacity, max 3 tries). Never switch keys, IPs or identities.
- Two blocks in 7 days for a grey source: set `source_health.enabled = false` and show it on the app's engine page. Only the founder can turn it back on.

### 18.1.6 No proxies, no evasion
- Create the shared `httpx.AsyncClient` with `trust_env=False` (ignores proxy environment variables) and no `proxy` argument.
- A unit test asserts the client has no proxy configured (Step 17.2.2).
- Forbidden libraries: anything that solves CAPTCHAs, any stealth plugin for Playwright, any proxy-rotation service. Add them to a `forbidden-deps` check in CI (a small script that fails if `pyproject.toml` or `package.json` contains them).

### 18.1.7 Kill switches
| Switch | Where | Effect |
|---|---|---|
| `settings.sources_enabled[source] = false` | app engine page | The adapter returns immediately with "disabled" |
| `source_health.enabled = false` | set by the engine after repeated blocks, or by the founder | Same as above |
| `settings.segments_enabled[segment] = false` | app engine page | No new research or leads for that segment |
| `settings.providers_enabled[provider] = false` | app engine page | The AI router skips that provider and uses fallbacks (Appendix C) |
| GitHub Actions workflow disabled | GitHub UI | Nothing runs (emergency stop) |

## 18.2 Personal data: minimise, retain briefly, delete on request

### 18.2.1 What we store
| Store | Do not store |
|---|---|
| Business name, website, address, business phones and emails the business published | Personal mobile numbers that the person did not publish for the business |
| Decision maker's name and role as written on the business's own pages | Photos, date of birth, home address, family details |
| Quotes from the business's own pages and job posts | Content from personal social profiles |
| Derived flags from Google reviews ("reviews mention unanswered calls") | Review text or reviewer names |

### 18.2.2 Retention
| Data | Keep for | Then |
|---|---|---|
| `pages.text` for businesses that became leads | 180 days | Delete text, keep URL, hash, fetched date |
| `pages.text` for rejected, dormant or never-qualified businesses | 90 days | Delete row |
| Google Places content (rating, review count, phone from listing) | 30 days | Nightly job sets them to null unless refreshed (A.4.4); derived fields stay |
| `facts` | while the business exists | Deleted with the business |
| `suppression` | forever | Never deleted (it is what keeps people safe from repeat contact) |
| `activities`, `leads` | while useful for learning (at least 2 years) | Archive or delete on request |
| `costs`, `runs` | 1 year | Delete |

The monthly workflow (Step 14) runs `nlead health --prune` to apply this table.

### 18.2.3 Deletion requests ("forget me")
1. The founder clicks **Forget this business** on the lead page (admin only).
2. The engine deletes the business's `contacts`, `facts`, `pages`, `signals`, `scores`, `leads`, `activities`, `feedback` and `source_records`.
3. It adds the phone numbers, emails and web domain to `suppression` with reason `forget_request`, so the business is never collected again.
4. It writes one `runs` row of kind `manual` recording the deletion (no personal data in the row).
5. Respond to the requester within 7 days.

## 18.3 Opt-outs and wrong contacts
- Stage `wrong_contact`, or a reply like "stop" or "do not message", leads to an entry in `suppression`: the phone in E.164 and the reason. If the business itself asked to stop, also add its `web_domain`.
- The app has a **Do not contact** button that writes to `suppression` and sets `contacts.do_not_contact = true`.
- The pre-filter (Step 8) drops any business whose phone, email or domain is in `suppression`. The message step (Step 12) refuses to write a message for a suppressed contact (a second safety net).
- Suppression is checked again just before a lead is written to the sheet and the app (third safety net).

## 18.4 Country rules (read before enabling a country)

This is guidance for a non-lawyer. Get a short legal check before enabling any wave 2 or wave 3 country.

| Country | Main law | What it means for us | Before enabling |
|---|---|---|---|
| India | Digital Personal Data Protection Act 2023 and Rules 2025 (core duties phase in to about May 2027) | Data the person made public is exempt (s.3(c)(ii)), but keep data minimal and purposeful; honour deletion and opt-out | Privacy page on nument.in names a contact for data requests |
| UAE | Federal Decree-Law 45 of 2021 (PDPL); DIFC and ADGM have their own laws | Consent is the main legal basis, with exceptions; keep B2B data minimal; honour opt-outs fast | Check whether targeting DIFC or ADGM firms needs extra steps |
| Saudi Arabia | Personal Data Protection Law (enforced from Sept 2024) | Consent based; strict rules on transferring data out of the Kingdom (our database is in Mumbai) | Legal check on cross-border transfer before wave 2 |
| Qatar | Law 13 of 2016 | Electronic marketing generally needs prior consent | Legal check; prefer email to a business address with easy opt-out |
| UK | UK GDPR and PECR | Cold email to corporate addresses is allowed with clear identity and opt-out; sole traders and partnerships count as individuals and need consent; need a legitimate interests assessment; may need an ICO registration and a UK representative | Write the legitimate interests assessment; check ICO fee and representative |
| Singapore | PDPA and the Do Not Call registry (Spam Control Act) | Business contact information is largely exempt from PDPA; marketing messages to Singapore phone numbers must be checked against the DNC registry | Check whether WhatsApp messages count as "specified messages" for DNC; plan DNC checks |
| US | TCPA, CAN-SPAM, state laws (for example Florida) | No automated calls or texts without consent; email must identify the sender, include a postal address and an opt-out honoured within 10 days | Email-first outreach; no SMS; legal check on state rules |
| Australia | Privacy Act, Spam Act 2003 | Commercial electronic messages need consent (inferred consent is narrow) and an unsubscribe | Legal check; likely email only to published business addresses |

The segment YAML for each country (Step 3) records the outreach channel (`whatsapp`, `email`, or both) and a `compliance_notes` field that the app shows on every lead page for that country.

## 18.5 Google Places terms
1. Store only `place_id` permanently (`businesses.place_id`).
2. Rating, review count, phone and website from Places are refreshed at most every 30 days (`businesses.places_fetched_at`). Older values are nulled by the prune job (18.2.2).
3. Never store review text or reviewer names. The `review_pain` signal stores a derived description and the Google Maps URL for the place (`https://www.google.com/maps/place/?q=place_id:<id>`), not a quote.
4. If the app shows a Google rating, it shows "Google" next to it (attribution).
5. Use only the official Places API (New) in the Balanced tier. The grey Maps scraper stays off.

## 18.6 WhatsApp sending guidance (for the founder)
The engine never sends. These rules protect the founder's number:
1. Send one by one from the WhatsApp Business app (or WhatsApp Web), never broadcast lists or bulk tools.
2. Start at 30 new chats per day per number. If almost nobody blocks or reports for a week, add about 10 per day each week, up to about 80 per day.
3. Send at 10:00 to 12:00 or 15:00 to 17:00 in the recipient's time zone (UAE is 1 hour 30 minutes behind India). Not on Sundays or public holidays there (Friday afternoons in the Gulf are quiet).
4. Use the business profile: Nument logo, description, website.
5. If a message is not delivered for days, or WhatsApp warns about the account, stop new chats for 48 hours and tell the builder (Step 22 troubleshooting).
6. Maximum two follow-ups (day 3 and day 7 drafts in the app), and only if the first message was delivered.
7. Anyone who asks to stop goes to **Do not contact** immediately.

## 18.7 Security

### 18.7.1 Secrets
| Secret | Lives in | Never in |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | GitHub Actions secrets, Render server env | Browser code, `NEXT_PUBLIC_*` variables, the repo |
| `DATABASE_URL` | GitHub Actions secrets, local `.env` | The repo, logs |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_MAPS_API_KEY` | GitHub Actions secrets, local `.env` | The repo, the web app |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | GitHub Actions secret | The repo; locally use `GOOGLE_SERVICE_ACCOUNT_FILE` pointing outside the repo |
| `GH_DISPATCH_TOKEN` | Render server env | Browser code |
| `BACKUP_PASSPHRASE` | GitHub Actions secret, and a printed copy kept safely by the founder | Anywhere else |

Rules:
1. `.env` and `*.json` key files are in `.gitignore`. Add a secret scanner (gitleaks) as a pre-commit hook and a CI job.
2. Logs never print keys, phone numbers in full, or emails in full. structlog has a redaction processor that masks values matching key patterns, phone numbers (keep the last 4 digits) and emails (keep the domain).
3. The web app reads the service role key only in server code (route handlers and server actions), and only for admin actions that RLS cannot express (creating users, triggering workflows).

### 18.7.2 Database security
- RLS is enabled on every table (Step 2). The engine uses the service role and bypasses RLS; the web app uses the user's session and is limited by RLS.
- Roles: `admin` (founder), `caller` (Aditya: no money, no costs, no settings), `viewer` (read only).
- Sign-ups are disabled; only the admin creates users (Step 15).

### 18.7.3 Accounts
- Turn on two-factor authentication for GitHub, Supabase, Render, Google Cloud, Google AI Studio and OpenAI accounts.
- The fine-grained `GH_DISPATCH_TOKEN` has only "Actions: read and write" on this one repository and expires in 90 days (calendar reminder to renew).

### 18.7.4 Dependencies
- `.github/dependabot.yml` checks `pip` (uv), `npm` (pnpm) and `github-actions` weekly.
- Pin GitHub Actions to commit SHAs.
- Merge Dependabot pull requests only when CI (including `eval-gate` if triggered) is green.

### 18.7.5 Access reviews and key rotation
| When | What |
|---|---|
| **Now, before building** | Rotate the old Google service-account key that was pasted in a chat in Oct 2026: create a new key for the same service account, store it as `GOOGLE_SERVICE_ACCOUNT_JSON`, then delete the old key in Google Cloud console (IAM, Service accounts, Keys). Revoke the old GitHub personal access token that was pasted in a chat (github.com, Settings, Developer settings, Tokens). |
| Monthly | Review app users and roles in the app settings page; remove anyone who left |
| Quarterly | Rotate Gemini, OpenAI and Maps keys and the service-account key; renew `GH_DISPATCH_TOKEN`; test a backup restore (Step 22.4) |
| Immediately on any leak | Follow 18.8 |

## 18.8 Incident response

| Incident | Contain (first 15 minutes) | Fix | Record |
|---|---|---|---|
| A key or secret leaked | Revoke or rotate it at the provider; update GitHub and Render secrets | Find how it leaked; add a scanner rule | `docs/incidents.md` |
| Personal data exposed (for example a public link to data) | Remove access; disable the affected feature | Assess who is affected; under India's DPDP Rules a personal data breach must be reported to the Data Protection Board and affected people (verify the timeline at build) | `docs/incidents.md` |
| A website owner or platform complains | Disable that source (kill switch) | Reply politely within 48 hours; delete their data if asked (18.2.3) | `docs/incidents.md`, add to exclusions |
| WhatsApp restricts the founder's number | Stop new chats for 48 hours | Lower daily volume (18.6); review message similarity and complaints | Weekly report |
| Wrong person contacted repeatedly | Add to suppression | Find why the phone was attached to the business; fix verification | Golden set: add as a bad example |
| Spend spike | The budget guard stops optional tasks; if needed, disable workflows | Find the task that overspent in `costs`; fix limits | Weekly report |

## 18.9 Done when
- [ ] `polite_get` is the only network path for scraping; a test proves never-fetch hosts raise before any request.
- [ ] Blocks set `blocked_until` and stop the source for the run; two blocks in 7 days disable a grey source.
- [ ] The HTTP client has no proxy; the forbidden-dependency check runs in CI.
- [ ] All kill switches in 18.1.7 work from the app engine page (tested on dev).
- [ ] The prune job applies the retention table and nulls Places content older than 30 days.
- [ ] "Forget this business" and "Do not contact" work end to end, and suppressed contacts never reach the sheet or app.
- [ ] The old service-account key is deleted and the old GitHub token is revoked.
- [ ] Two-factor authentication is on for every account in 18.7.3; gitleaks runs in CI.
- [ ] `docs/incidents.md` exists with the table in 18.8.

---

---

# Step 19: Cost controls

## 19.1 Goal and rules
- Spend on AI and paid APIs never goes over **₹750 a day** (`settings.daily_cap_inr`).
- At **80%** of the cap (`settings.alert_pct`), the founder is alerted once that day.
- When money runs short, the cheapest-to-lose work stops first. Messages for the best leads are the last thing to stop.
- Free allowances (Google Places, Gemini grounded search) are counted and never exceeded by accident.
- Every paid call is logged with its tokens and price, so the cost of each lead is known.

## 19.2 `engine/config/prices.yaml`
Prices change often. Verify every number on the official pricing pages on the build day and update `verified_on`.

```yaml
verified_on: 2026-11-12              # update on the build day
fx_inr_per_usd: 88                   # default; the settings table can override it
batch_discount: 0.5                  # Gemini and OpenAI batch APIs (about half price)

models:                              # USD per 1M tokens
  gemini-3.1-pro:        {provider: gemini, input: 2.00, output: 12.00, thinking_counts_as_output: true}
  gemini-3-flash:        {provider: gemini, input: 0.50, output: 3.00,  thinking_counts_as_output: true}
  gemini-3.1-flash-lite: {provider: gemini, input: 0.25, output: 1.50}
  gpt-5-mini:            {provider: openai, input: 0.25, output: 2.00}
  gpt-5-nano:            {provider: openai, input: 0.05, output: 0.40}
  gpt-5.4:               {provider: openai, input: 2.50, output: 15.00}

search:
  gemini_grounding:  {free_per_month: 5000, usd_per_1k: 14.0}     # billed per search query the model runs
  openai_web_search: {usd_per_1k: 10.0}                            # plus search content tokens

places:                              # USD per 1,000 calls, free calls per month, by billing region
  india:
    text_search_ids_only:       {usd_per_1k: 0.0,  free_per_month: null}   # unlimited
    place_details_enterprise:   {usd_per_1k: 6.00, free_per_month: 7000}
    place_details_atmosphere:   {usd_per_1k: 7.50, free_per_month: 7000}
  global:
    text_search_ids_only:       {usd_per_1k: 0.0,  free_per_month: null}
    place_details_enterprise:   {usd_per_1k: 20.0, free_per_month: 1000}   # verify on the build day
    place_details_atmosphere:   {usd_per_1k: 25.0, free_per_month: 1000}   # verify on the build day

pagespeed: {usd_per_1k: 0.0, daily_free: 25000}
```

## 19.3 Cost logging
Every call to a paid or quota-limited service goes through one function, which inserts a row into `costs`. Free calls are logged too (with `usd = 0`) so that quotas can be counted from the same table.

| `costs.provider` | `costs.task` values | Notes |
|---|---|---|
| `gemini` | AI task names from A.12.5 | Tokens from `usage_metadata` (prompt, candidates, thoughts) |
| `openai` | AI task names from A.12.5 | Tokens from `usage` (input, output, reasoning) |
| `google_places` | `places_text_search`, `places_details`, `places_details_reviews` | `calls = 1` per request, usd from the region's price after the free allowance |
| `google_search` | `grounded_search` | Count of search queries the model ran (from the grounding metadata) |
| `pagespeed` | `pagespeed` | Free; logged for the daily count |

For batch jobs, cost is logged when results are **collected**, using the real token counts in each result and `batch_discount`.

## 19.4 Database views for spend and quotas
Add to a new migration `0006_cost_views.sql` (skip any view Step 2 already created):

```sql
-- Today's spend in IST
create or replace view v_spend_today as
select coalesce(sum(inr), 0)::numeric(12,2) as inr,
       coalesce(sum(usd), 0)::numeric(12,4) as usd
from costs
where (at at time zone 'Asia/Kolkata')::date = (now() at time zone 'Asia/Kolkata')::date;

-- Calls per task today (quota counting)
create or replace view v_quota_today as
select provider, task, sum(calls)::int as calls
from costs
where (at at time zone 'Asia/Kolkata')::date = (now() at time zone 'Asia/Kolkata')::date
group by provider, task;

-- Calls per task this month (free monthly allowances)
create or replace view v_quota_month as
select provider, task, sum(calls)::int as calls
from costs
where date_trunc('month', at at time zone 'Asia/Kolkata') = date_trunc('month', now() at time zone 'Asia/Kolkata')
group by provider, task;

-- Daily cost report
create or replace view v_costs_daily as
select (at at time zone 'Asia/Kolkata')::date as day, provider, task,
       sum(calls) as calls, sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens,
       sum(usd)::numeric(12,4) as usd, sum(inr)::numeric(12,2) as inr
from costs
group by 1, 2, 3;
```

## 19.5 `budget.py`

### 19.5.1 Interface
```python
"""Spend tracking and the daily cap. Every paid call is estimated before it is made and logged after."""
from __future__ import annotations

import dataclasses as dc
import math
from functools import lru_cache
from pathlib import Path

import yaml


class BudgetStop(Exception):
    """Raised inside a phase when the cap is reached; the phase stops cleanly, the run becomes 'partial'."""


# Lower number = stops first. Free work (verify, score, sheet sync, health) is never gated.
PRIORITY = {
    "fit_only_research": 1,
    "low_priority_research": 2,
    "grounded_search": 3,
    "research": 4,
    "extract": 4,
    "judge": 4,
    "message": 5,
}
# A priority may start only while today's spend is under this share of the cap.
THRESHOLD = {1: 0.60, 2: 0.75, 3: 0.85, 4: 0.95, 5: 1.00}


@lru_cache
def prices() -> dict:
    return yaml.safe_load((Path(__file__).parents[2] / "config" / "prices.yaml").read_text())


def estimate_tokens(text: str, script: str = "latin") -> int:
    """Rough token count before a call: about 4 characters per token for English, about 2 for Devanagari or Arabic."""
    per = 2 if script in ("devanagari", "arabic") else 4
    return math.ceil(len(text) / per)


def llm_cost_usd(model: str, input_tokens: int, output_tokens: int, batch: bool = False) -> float:
    p = prices()["models"][model]
    usd = input_tokens / 1e6 * p["input"] + output_tokens / 1e6 * p["output"]
    return usd * (prices()["batch_discount"] if batch else 1.0)


@dc.dataclass
class BudgetGuard:
    conn: object
    run_id: str

    def cap_inr(self) -> float: ...                      # settings.daily_cap_inr (750)
    def fx(self) -> float: ...                           # settings.fx_inr_per_usd or prices.yaml default
    def spent_inr(self) -> float: ...                    # select inr from v_spend_today

    def allow_phase(self, priority: int) -> bool:
        """May a phase of this priority start now?"""
        return self.spent_inr() < THRESHOLD[priority] * self.cap_inr()

    def check(self, priority: int, est_usd: float) -> None:
        """Before each paid call: raise BudgetStop if this call would cross the threshold for its priority."""
        projected = self.spent_inr() + est_usd * self.fx()
        if projected > THRESHOLD[priority] * self.cap_inr():
            raise BudgetStop(f"priority {priority} blocked at ₹{projected:.0f} of ₹{self.cap_inr():.0f}")
        self._maybe_alert(projected)

    def record(self, provider: str, model: str | None, task: str, *, input_tokens: int = 0,
               output_tokens: int = 0, calls: int = 1, usd: float = 0.0) -> None:
        """Insert one row into costs (usd and inr). Called after every paid or quota-limited call."""
        ...

    def quota_left(self, provider: str, task: str, *, per_day: int | None, per_month: int | None) -> int:
        """Remaining calls today and this month (min of both), from v_quota_today and v_quota_month."""
        ...

    def _maybe_alert(self, projected_inr: float) -> None:
        """At alert_pct of the cap, raise the alert once per IST day (settings.budget_alert_day)."""
        ...
```

### 19.5.2 How the AI router uses it (Step 4)
```python
est_in = estimate_tokens(prompt_text) + task.overhead_tokens
est_out = task.max_output_tokens * (1.5 if task.thinking else 1.0)
guard.check(PRIORITY[task.budget_class], llm_cost_usd(task.model, est_in, est_out, batch=task.batch))
response = provider.call(...)
guard.record(provider.name, task.model, task.name,
             input_tokens=response.usage.input, output_tokens=response.usage.output + response.usage.thinking,
             usd=llm_cost_usd(task.model, response.usage.input,
                              response.usage.output + response.usage.thinking, batch=task.batch))
```
For a batch, the estimate covers the whole batch at submission (sum of item estimates). If the whole batch does not fit, submit only as many items as fit, best leads first.

## 19.6 The degradation ladder
| Today's spend (share of ₹750) | What still runs | What stops |
|---|---|---|
| Under 60% (₹450) | Everything | Nothing |
| 60% to 75% | Everything except fit-only research | Research of fit-only businesses (no signal) |
| 75% to 85% (₹637) | Research of businesses with signals, extraction, grounded search, judge, messages | Low-priority research (lowest signal points or smallest can-pay proxies) |
| 85% to 95% (₹712) | Research of strong-signal businesses, extraction, judge, messages | Grounded searches (public asks, owner lookups) |
| 95% to 100% | Messages only | Judge (leads keep their rule grade, marked "judge skipped") and new research |
| 100% (₹750) | Free work only | Messages (leads wait for the next morning with the fallback template hidden from the sheet) |
| Never gated | Verify, score, sheet sync, health, reports | These cost nothing |

The alert fires the first time the projected spend crosses 80% (₹600) on an IST day.

## 19.7 Daily quotas
| Quota | Setting key | Default | Enforced by |
|---|---|---|---|
| Businesses researched | `research_per_day` | 300 | Prefilter queue size (Step 8) |
| Places Details, India | `places_details_daily_cap` | 230 | `guard.quota_left("google_places", "places_details", per_day=230, per_month=7000)` |
| Places Details with reviews, India | `places_reviews_daily_cap` | 230 | Same, task `places_details_reviews` |
| Places Details, abroad | `places_details_daily_cap_global` | 30 | Same, region `global`, per_month 1000 |
| Gemini grounded searches | `grounding_daily_cap` | 160 | `quota_left("google_search", "grounded_search", per_day=160, per_month=5000)` |
| PageSpeed checks | `pagespeed_daily_cap` | 600 | Free; the cap keeps run time down |

Also set the same daily caps in the Google Cloud console (APIs and Services, Places API (New), Quotas) so that even a bug cannot exceed them. Set a monthly usage limit in the OpenAI dashboard (about $30) and a budget alert in Google Cloud Billing (₹100).

## 19.8 Reports
- **Morning summary** (job summary and app Health page): spend today, spend this month, spend by task, cost per researched business, cost per new lead.
- **Weekly report** (Step 16): adds cost per reply, per meeting and per won client by segment.
- **Monthly report:** `nlead report costs --month 2026-12` prints a table by provider and task, with totals in ₹ and $, and the month's free allowance use (Places, grounded search).

## 19.9 Tuning levers (in order of impact)
1. **Batch everything that can wait overnight** (extraction is already batched). About half price.
2. **Trim inputs:** strip menus, footers and repeated blocks before extraction; cap at 16K tokens per business; read at most 8 pages.
3. **Lowest thinking level** for extraction and classification tasks (verify the parameter name per model on the build day).
4. **Judge only the top half** (already the Balanced default). Raise the cut if judge spend grows.
5. **Cache by content hash:** if a page's `text_hash` has not changed since the last extraction, reuse the facts.
6. **Skip research of businesses checked in the last 90 days** unless a new signal arrived (Step 8).
7. **Places IDs-only search is free:** only call Details for businesses that pass the rules.

## 19.10 Tests
- `test_threshold_ladder`: with a fake `v_spend_today`, each priority is allowed or blocked exactly at the thresholds in 19.6.
- `test_batch_cost`: batch cost is half the sync cost for the same tokens.
- `test_quota_left`: per-day and per-month limits both apply; the smaller wins.
- `test_alert_once`: crossing 80% twice in one day alerts once.

## 19.11 Done when
- [ ] `engine/config/prices.yaml` exists with today's verified prices and `verified_on` set.
- [ ] `budget.py` is used by the AI router (Step 4) and every Places and grounded-search call (Step 5).
- [ ] Every paid call writes a `costs` row with tokens, usd and inr.
- [ ] `v_spend_today`, `v_quota_today`, `v_quota_month` and `v_costs_daily` exist.
- [ ] A forced low cap (set `daily_cap_inr` to 5 in dev) stops phases in the order of 19.6 and the run ends `partial`.
- [ ] The 80% alert appears once (job summary, Health page, optional email).
- [ ] Daily quotas are also set in the Google Cloud console, and an OpenAI monthly limit is set.

---

---

# Step 20: Migrating the old lead engine

## 20.1 Goal
Move everything of value from the old folder `~/Desktop/lead-engine` into the new database **once**, without losing the founder's work:
- the 13 leads contacted on 12 Nov 2026 (12 Contacted, 1 Wrong contact: HomeTrust, lead `A-0045`)
- the researched lead records and their messages
- the suppression and skip lists

Then switch both Google Sheets from the old sync to the new one, and retire the old Mac job. The old folder is never edited during or after the migration; it is only read, then archived.

## 20.2 What exists in the old folder
| Old file | What it holds | Size on 12 Nov 2026 |
|---|---|---|
| `data/leads.jsonl` | One JSON per lead: org, people, website, phones, emails, signals, evidence, grade, win chance, ticket estimates, `wa_msg`, `wa_alt`, `wa_angle`, `wa_facts`, site check fields, `listed` flag | 102 leads, 55 listed |
| `data/reviews.jsonl` | People's edits per lead: `stage`, `wa_at`, `call_at`, `d3_at`, `d7_at`, `meeting_at`, `deal_value`, `notes`, `history[]` | 13 leads with stage beyond New |
| `data/suppression.csv` | Do-not-contact list | Header only |
| `data/skip_list.txt` | Businesses already researched or rejected (do not re-research) | About 520 rows |
| `data/manual_edits.jsonl` | History of corrections | About 450 edits (kept for reference, not imported) |
| `data/sheet.json` | Sheet ids, service account path, associate name | Used to fill env vars |
| `data/decisions.md`, `data/customer_plan.md`, `data/whatsapp_playbook.md` | Decisions and playbooks | Copied into `docs/` of the new repo, not the database |
| `data/cache/sheet_snapshot_*.json` | Old per-sheet snapshots | Not imported (new snapshots are seeded from the sheet itself, 20.6) |

## 20.3 Mapping rules

### 20.3.1 Segments for old leads
Old leads were mixed (clinics, retail, law, real estate, manufacturing, education, fitness). Classify each into a wave 1 segment where it clearly fits. Leads that do not fit any wave 1 segment go to a **dormant** segment `legacy-in` (`enabled = false`), so they keep their history but the engine never searches for more like them.

| Old lead looks like | New segment |
|---|---|
| Clinic, diagnostic centre, dermatology, dental, IVF, therapy | `clinics-in` |
| Real estate broker or developer | `realestate-in` |
| Coaching, academy, school, edtech | `education-in` |
| Anything else (D2C, law firm, manufacturing, gym, startups) | `legacy-in` |

Keep the rule list in `ops/migrate_legacy.py` as an explicit dict of old lead id to segment for the 55 listed leads (reviewed by hand once). The rest use keyword rules on the org name and the `why` text.

### 20.3.2 Field map
| Old field | New table.column | Rule |
|---|---|---|
| `lead_id` | `source_records(source='legacy', source_key=lead_id)` | This row is the id map: old id to `business_id` |
| `org` | `businesses.name`, `norm_name` | Clean legal suffixes (port `clean_org()`) |
| `website` | `businesses.website`, `web_domain` | `tldextract` registrable domain |
| `city` / address text | `businesses.city`, `address` | If missing, leave blank |
| `country` "India" | `businesses.country = 'IN'` | |
| `name`, `dm_name`, `dm_role`, `role` | `contacts.name`, `role`, `is_decision_maker` | One contact per person |
| `phone`, `phone_national`, `phone_status`, `phone_source_url`, `phone_quote` | `contacts.phone_e164`, `phone_type`, `verified`, `source_url`, `quote`, `source` | `phonenumbers` for E.164 and type. `source = 'website'` when the source URL is on the business's own domain, else `other` |
| `email`, `email_status`, `email_source_url` | `contacts.email`, `verified` | Only verified emails |
| `why_now_short`, `why_now_date`, `why_now_url`, `why_now_note`, `source` | `signals` | Type: hiring posts for builders give `hiring_builder`, front-desk posts give `hiring_frontdesk`, public asks give `public_ask`, funding gives `funding`. Expiry from A.12.3 counted from `why_now_date`, so most old signals arrive already expired |
| `evidence_1..3`, `evidence_url_1..3`, `wa_facts[]` | `facts` | `model = 'legacy'`, `verified = false` until Step 10 re-verifies them on a fresh crawl |
| `team_size_band`, `has_tech_team`, `vendor_footer`, `site_*` | `facts` (one row per field) | Same, `model = 'legacy'` |
| `win_chance`, `grade`, `win_parts` | `scores` | `version = 'legacy-v1'`, `total = win_chance`, `grade` as is, `reasons = win_parts` |
| `wa_msg`, `wa_alt`, `wa_angle` | `leads.message`, `message_alt`, `angle` | `message_model = 'legacy'` |
| reviews `stage` | `leads.stage` | Old display label to the DB value with `canon_stage()`. Old labels ("Not reached", "Interested", "Meeting booked") map through the old `LEGACY` table first |
| reviews `wa_at`, `call_at`, `d3_at`, `d7_at`, `meeting_at` | same columns | ISO dates |
| reviews `deal_value` | `leads.deal_value_inr` | `parse_money_cell()` (13.7.6) |
| reviews `notes` | `leads.notes` | |
| reviews `history[]` | `activities` | `source = 'sheet'`, `type = 'stage_change'` or `edit`, `at` from the history entry |
| `listed` and grade A or B, or a reviews stage beyond New | creates a `leads` row | Others become businesses only (status `researched` or `rejected`) |
| `test_group` | `leads.test_group` | `{segment}:{pitch_mode}:{angle}` with `pitch_mode` from the signal type |

### 20.3.3 Suppression and skip list
- Every row of `suppression.csv` goes to `suppression` (phone to E.164, domain to `web_domain`).
- The Wrong contact lead (HomeTrust, `A-0045`): its phone goes to `suppression` with `reason = 'wrong_contact'`, and the contact gets `do_not_contact = true`. The lead keeps stage `wrong_contact`.
- `skip_list.txt`: each line that looks like a URL or domain becomes `web_domain`; other lines are names. Insert as `source_records(source='legacy_skip', source_key=line)`. Matching businesses (by domain, or by exact normalised name) get `status = 'rejected'`, `reject_reason = 'legacy_skip'`. The prefilter (Step 8) keeps rejected businesses out for 180 days.

## 20.4 `ops/migrate_legacy.py`

```python
"""One-time import from the old lead-engine folder. Read-only on the old folder. Safe to re-run: every insert
is an upsert keyed on source_records(source, source_key), so a second run changes nothing."""
from __future__ import annotations

import csv
import json
from pathlib import Path

LEGACY_ROOT = Path.home() / "Desktop" / "lead-engine"
LEGACY_STAGE = {"Not reached": "contacted", "Interested": "talking", "Meeting booked": "discovery_booked"}


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def migrate(conn, *, root: Path = LEGACY_ROOT, dry_run: bool = False) -> dict:
    leads = read_jsonl(root / "data" / "leads.jsonl")
    reviews = {r["lead_id"]: r for r in read_jsonl(root / "data" / "reviews.jsonl")}
    stats = {"businesses": 0, "contacts": 0, "signals": 0, "facts": 0, "scores": 0, "leads": 0,
             "activities": 0, "suppression": 0, "skips": 0, "unmapped_stages": []}
    with conn.transaction():
        for old in leads:
            biz_id = upsert_business(conn, old)                      # also writes source_records('legacy', lead_id)
            stats["businesses"] += 1
            stats["contacts"] += upsert_contacts(conn, biz_id, old)
            stats["signals"] += upsert_signals(conn, biz_id, old)
            stats["facts"] += upsert_facts(conn, biz_id, old)
            score_id = upsert_score(conn, biz_id, old)
            stats["scores"] += 1
            rev = reviews.get(old["lead_id"], {})
            if wants_lead(old, rev):
                lead_id = upsert_lead(conn, biz_id, score_id, old, rev, stats)
                stats["leads"] += 1
                stats["activities"] += import_history(conn, lead_id, rev)
        stats["suppression"] += import_suppression(conn, root / "data" / "suppression.csv")
        stats["suppression"] += suppress_wrong_contacts(conn)
        stats["skips"] += import_skip_list(conn, root / "data" / "skip_list.txt")
        if dry_run:
            raise RollbackDryRun(stats)                              # caught by the CLI, prints stats, rolls back
    return stats


def wants_lead(old: dict, rev: dict) -> bool:
    stage = (rev.get("stage") or "New").strip()
    return stage != "New" or (old.get("listed") and old.get("grade") in ("A", "B"))
```
Write `upsert_business`, `upsert_contacts`, `upsert_signals`, `upsert_facts`, `upsert_score`, `upsert_lead`, `import_history`, `import_suppression`, `suppress_wrong_contacts` and `import_skip_list` using the field map in 20.3.2. Every function uses `insert ... on conflict ... do update` so a re-run is harmless.

Add `scripts/legacy_segment_map.json` (old lead id to segment, reviewed by hand) next to the module and load it in `upsert_business`.

## 20.5 Verification
Run after the migration (prod) and compare with the old files:

```sql
-- 1. Every old lead has a business
select count(*) from source_records where source = 'legacy';                 -- = lines in leads.jsonl (102 on 12 Nov)

-- 2. Leads created
select count(*) from leads l join source_records r on r.business_id = l.business_id and r.source = 'legacy';

-- 3. The 13 contacted leads and their stages
select l.stage, count(*) from leads l where l.stage <> 'new' group by 1;    -- contacted 12, wrong_contact 1 (12 Nov)

-- 4. All 13 have wa_at = 2026-11-12
select count(*) from leads where stage <> 'new' and wa_at = date '2026-11-12';

-- 5. Messages carried over
select count(*) from leads where message is not null and message_model = 'legacy';

-- 6. HomeTrust is suppressed
select * from suppression where reason = 'wrong_contact';

-- 7. Skip list imported
select count(*) from source_records where source = 'legacy_skip';            -- about 520
```

Then compare by eye: open the old sheet's Pipeline tab and the new app's Leads page side by side for all 13 contacted leads. Stage, WA date and notes must match exactly.

A second run of `nlead migrate-legacy --env prod` must report zero inserts and zero updates.

## 20.6 Cutover of the Google Sheets
Do this in one sitting of about 30 minutes. Tell the founder and Aditya not to edit the sheets during it.

1. **Final old read-back.** Run the old sync once so the newest sheet edits reach `reviews.jsonl`:
   ```bash
   cd ~/Desktop/lead-engine && .venv/bin/python scripts/sync_sheet.py
   ```
2. **Stop the old Mac job** (do not delete it yet):
   ```bash
   launchctl bootout gui/$(id -u)/in.nument.sheet-sync
   launchctl print gui/$(id -u)/in.nument.sheet-sync 2>&1 | head -1    # should say it could not find the service
   ```
3. **Archive the old folder** (read-only copy):
   ```bash
   cd ~/Desktop && zip -qr "lead-engine-archive-$(date +%Y-%m-%d).zip" lead-engine -x "lead-engine/.venv/*" "lead-engine/data/cache/*"
   ```
4. **Migrate:** `nlead migrate-legacy --env prod --dry-run`, read the stats, then run it without `--dry-run`. Run the checks in 20.5.
5. **Seed the new snapshots from the current sheets**, so the first pull finds no edits:
   ```bash
   nlead sheet pull --env prod --seed-snapshots
   ```
   This reads both sheets, matches rows by the old lead id (the old sheets' hidden ID column holds the old id; the `legacy` source record maps it to the new lead) and writes `sheet_snapshots` rows equal to what the sheets show. It writes nothing to the leads.
6. **First push with the new engine:** `nlead sheet push --env prod`. The tabs keep their names, so links and bookmarks keep working. The hidden ID column now holds the new uuid.
7. **Check:** open both sheets. Same leads, same stages, same dates, same notes, same design. The caller sheet has no money.
8. **Turn on the schedules:** enable the GitHub workflows (Step 21).

## 20.7 Retiring the old engine (after 7 clean days)
Only after 7 consecutive days of successful night, morning and sheet-sync runs on prod:

```bash
# remove the old schedule file (the job was already stopped in 20.6 step 2)
mkdir -p ~/Library/LaunchAgents/disabled
mv ~/Library/LaunchAgents/in.nument.sheet-sync.plist ~/Library/LaunchAgents/disabled/

# make the old folder read-only, so nothing can write to it by mistake
chmod -R a-w ~/Desktop/lead-engine/data ~/Desktop/lead-engine/scripts
```
Keep the archive zip for at least 6 months. Copy `data/decisions.md`, `data/customer_plan.md` and `data/whatsapp_playbook.md` into the new repo's `docs/` folder (they are the history of every decision).

## 20.8 Rollback
If the new sync misbehaves during the first 7 days:
1. Disable the new workflows (Actions tab, each workflow, "Disable workflow").
2. Restore the old schedule: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/in.nument.sheet-sync.plist` (or from the `disabled/` folder).
3. Run the old sync once. It rebuilds both sheets from `reviews.jsonl`.
4. Edits made in the new app during those days are in the new database's `activities` table. Re-apply them by hand, or with `nlead export-edits --since <date>` (a small helper that prints them as a list).

## 20.9 Pitfalls
- **Never write to the old folder from the new code.** `migrate_legacy.py` opens files read-only.
- **Old hidden IDs vs new IDs.** Before the first new push, the sheets carry old ids (`A-0051`). The seed step must map them through `source_records('legacy', ...)`. After the first new push, they carry uuids.
- **Old dates as text.** Some old `wa_at` values are ISO strings and some are sheet serial numbers. Normalise both.
- **Duplicate businesses.** Old records may duplicate businesses the new universe finds later. Entity resolution (Step 6) merges them by domain and phone; the `legacy` source record stays attached to the surviving business.
- **The 12 Nov 2026 messages** included a trailing "No rush, reply whenever it suits." line written for late-night sending. Keep the stored text as it was sent, for the record. New messages follow Step 12.

## 20.10 Done when
- [ ] `ops/migrate_legacy.py` and `scripts/legacy_segment_map.json` exist; the dry run prints stats that match the old files.
- [ ] All checks in 20.5 pass on prod, and a second run changes nothing.
- [ ] The 13 contacted leads show the same stage, WA date and notes in the app and in both sheets.
- [ ] HomeTrust's number is in `suppression` with `wrong_contact`.
- [ ] The old launchd job is stopped and the first new push succeeded with snapshots seeded.
- [ ] After 7 clean days: the old plist is moved to `disabled/`, the old folder is read-only, the archive zip exists, and the three decision documents are in `docs/`.

---

# Step 21: Go-live

**Goal:** switch from the old lead engine to the new system without losing a single lead or stage, with a tested way back.

**You need first:** Steps 0 to 20 done on dev, evals passing (Step 17), legacy import script ready (Step 20).

## 21.1 Pre-flight checklist (the day before the first dry run)
| # | Check | How |
|---|---|---|
| 1 | All migrations applied to dev and prod | `npx supabase db push` to each project, then compare `supabase migration list` |
| 2 | Admin user (founder) and caller user (Aditya) exist on prod with the right roles | App settings page, or Supabase dashboard + `profiles` row |
| 3 | GitHub secrets set for dev and prod (A.12.7) | Repo settings, Secrets and variables, Actions |
| 4 | Places API quotas set per day (A.10.2) | Google Cloud console, Places API (New), Quotas |
| 5 | Budget settings on prod: `daily_cap_inr = 750`, `alert_pct = 80`, `research_per_day = 100` for the first 3 days | App engine page or SQL on `settings` |
| 6 | `providers_enabled` matches reality (today: `{"gemini": true, "openai": false}`) | App engine page |
| 7 | Staging sheet (`SHEET_STAGING_ID`) exists and the service account can edit it | Share the sheet with the service-account email |
| 8 | Render web app deployed and login works for both users | Open the URL, log in as each |
| 9 | `nlead health --env dev` and `--env prod` are all green | Terminal or the health workflow |
| 10 | The old launchd job on the founder's Mac is still running (it stays until cutover) | `launchctl print gui/$(id -u)/in.nument.sheet-sync` |

## 21.2 Dry-run nights on dev (2 nights)
1. **Night 1:** trigger `night.yml` and `morning.yml` manually (workflow_dispatch) with `env = dev`, `limit = 100`, writing to the staging sheet only.
2. **Morning after night 1:** check:
   - [ ] Both runs finished with status `ok` (or `partial` with understood reasons).
   - [ ] Spend in `costs` is under ₹300 for 100 businesses.
   - [ ] At least 20 leads graded A or B; every lead has a message that passes lint.
   - [ ] The founder reads 20 leads in the app and marks thumbs up or down. Target: 15 or more thumbs up.
   - [ ] The staging sheet looks the same as today's design (Today, Pipeline, Lead details tabs).
   - [ ] Changing a stage in the app shows in the staging sheet after the next sheet sync, and the reverse.
3. Fix anything found. Re-run only the failed steps (every step is idempotent).
4. **Night 2:** same, with `limit = 300`. Check the same list, plus: total runtime of both runs is under 60 minutes (GitHub minutes budget, Step 14.6).
5. Build the golden set from these two nights (Step 17.3) and run the full eval. All thresholds must pass before cutover.

## 21.3 Cutover to prod (one evening, about 2 hours)
1. Ask the founder to stop editing the old sheets for 2 hours.
2. Run the old sync one last time on the Mac so the old data store has the latest stages: `cd ~/Desktop/lead-engine && .venv/bin/python scripts/sync_sheet.py`.
3. Run the legacy import into prod: `uv run nlead migrate-legacy --env prod` (Step 20). Check counts: leads, stages, contacted dates, notes, wrong contacts all match.
4. Stop the old daily job on the Mac:
   ```
   $ launchctl bootout gui/$(id -u)/in.nument.sheet-sync
   ```
   Keep the plist file and the old folder for 30 days (needed for rollback).
5. Point the new sheet sync at the real sheets: set `SHEET_MASTER_ID` and `SHEET_CALLER_ID` in the prod GitHub secrets.
6. Run `nlead sheet push --env prod` once by hand. Open both sheets and check: all old leads present with their stages, design intact, caller sheet has no money columns.
7. Enable the schedules for prod (the workflows read `APP_ENV = prod`).
8. Tell the founder: "From tomorrow, new leads arrive by 07:30 in the app and the sheet."

## 21.4 First 14 days: daily checks (10 minutes a day for the builder)
| Day | Volume setting | Check |
|---|---|---|
| 1 to 3 | `research_per_day = 100` | Runs ok; leads count and grade mix; spend vs ₹750 cap; any source blocked; sheet and app show the same leads |
| 4 to 7 | 200 | Same, plus wrong contact rate under 5% from the founder's marks; message similarity warnings |
| Day 7 | | Mini review with the founder: thumbs up share, messages he edited, anything annoying in the app |
| 8 to 14 | 300 if day 7 review is good | Same as above, plus GitHub Actions minutes used vs 2,000 |
| Day 14 | | Go or no-go for full volume: quality targets in A.1.5 met; first weekly report delivered |

## 21.5 Rollback plan
Use this if the new system is producing bad leads or breaking the founder's sheets in the first 30 days.
1. Disable the new workflows (GitHub, Actions, each workflow, Disable). This stops all writes.
2. Restore the sheets from Google Sheets version history (File, Version history) to the version just before cutover. Name that version "Before cutover" during step 21.3.6 so it is easy to find.
3. Re-enable the old Mac job:
   ```
   $ launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/in.nument.sheet-sync.plist
   ```
4. Any stage changes made in the new app after cutover: export them (`nlead report weekly` includes a stage change list, or query `activities` since cutover) and re-apply them in the old sheet by hand.
5. Fix the problem on dev, re-run Step 21.2, and cut over again.

## 21.6 Done when
- [ ] Two dry-run nights passed all checks in 21.2.
- [ ] Full golden eval passed.
- [ ] Legacy import counts match exactly.
- [ ] The old launchd job is stopped; the new schedules run on prod.
- [ ] 14-day checks are complete and the day-14 decision is recorded in the weekly report.

---

---

# Step 22: Operations runbook

**Goal:** a short routine that keeps the engine healthy, plus a table for fixing the common problems.

## 22.1 Daily (5 minutes, founder or builder)
1. Open the app **Engine** page:
   - Last night run and this morning run: both `ok`?
   - Leads added today: count and A/B mix.
   - Spend today vs the ₹750 cap.
   - Any source blocked or disabled?
2. Open **Today**: send the messages (founder).
3. If anything is red, check 22.5 below or tell the builder.

## 22.2 Weekly (Monday, 30 minutes)
1. Read the weekly report (Insights, Weekly report).
2. Act on "scale" and "cut" suggestions: change segment toggles or quotas on the Engine page.
3. Check the 5 audit leads (Leads, filter "Audit this week") and mark each correct or wrong.
4. Promote 5 to 10 thumbed leads into the golden set.
5. Check GitHub Actions minutes used this month (GitHub, Settings, Billing and plans) and Supabase database size (Supabase dashboard, Reports).

## 22.3 Monthly (first Monday, 1 hour)
1. Confirm the monthly universe refresh ran and picked up the new Overture release (Engine page, last monthly run).
2. Compare `engine/config/prices.yaml` with the official Gemini, OpenAI and Google Maps pricing pages; update and commit if changed.
3. Merge green Dependabot pull requests.
4. Review the suppression list and any deletion requests.
5. Review app users and roles (Step 18.7.5).
6. Cost review: month spend vs budget; cost per good lead; per meeting.
7. Check Places API usage vs free caps (Google Cloud console, APIs and services, Metrics).

## 22.4 Quarterly (half a day)
1. Rotate keys (Step 18.7.5).
2. Restore test: restore the latest encrypted backup into a scratch Supabase project or a local Postgres, and check row counts. Delete the scratch database after.
3. Model review: run the full golden eval with any newer, cheaper models; switch in `tasks.yaml` only if all thresholds still pass.
4. Re-check 5 hand-checked golden facts (Step 17.3.4).
5. Re-read the country rules in Step 18.4 for enabled countries.

## 22.5 Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No new leads this morning; Engine page shows no night run | GitHub Actions schedule did not fire (delayed or disabled), or the repo had no activity for 60 days (GitHub disables schedules on inactive repos) | Check the Actions tab; re-enable the workflow; trigger `night.yml` and `morning.yml` manually; the weekly workflow's commit of the report keeps the repo active |
| Runs fail with "connection refused" or database timeouts | Supabase free project paused after 7 days idle (or during maintenance) | Restore the project from the Supabase dashboard; the nightly runs keep it active once restored |
| Universe or signals step logs "quota exceeded" for Places | Daily Places quota reached | Normal at the cap; the step continues tomorrow. If it happens before midnight every day, lower the number of new cities per night in the segment YAML |
| Morning run says "batch not ready" | The AI provider's batch job is still running (batches can take hours) | The morning run waits up to 20 minutes, then processes what is ready and leaves the rest for the next morning. If a batch is older than 24 hours, `nlead extract collect --force-sync` re-runs those items synchronously (counts toward the cap) |
| A stage changed in the sheet did not reach the app (or the reverse) | Sheet sync skipped (disabled, failed, or a conflict) | Check the last `sheet_sync` run; conflicts are listed as activities with `source = sheet`; latest timestamp wins. Re-run `nlead sheet sync` |
| Sheet shows an error cell or broken formatting | A sheet push stopped half way, or someone edited a formula column | Re-run `nlead sheet push`; the push rebuilds tabs only after a full successful build. Formula columns are protected with a warning |
| A source shows "blocked" on the Engine page | The site returned a 403, 429 or a challenge page | Do nothing for 7 days (it retries after `blocked_until`). Never try to get around a block. If it is a grey source blocked twice, leave it disabled |
| Spend jumped near the cap early in the day | A task looped, or a price changed | Check `costs` by task for today; the guard already stopped optional tasks. Fix the cause; check `prices.yaml` |
| Founder or Aditya cannot log in | Wrong password, user removed, or session cookie problem | Admin resets the password from the app settings page (or Supabase dashboard, Authentication, Users). Clear cookies |
| App takes 30 to 60 seconds to open | Render free tier was asleep (cold start) | Expected on the free plan. Upgrade the web service to Starter (always on) if this bothers the founder |
| Monthly run fails reading Overture | The release path changed (old releases are removed after about two months) | `overture.py` reads the latest release from the STAC catalog; if the catalog moved, update the catalog URL in config and re-run `nlead universe --monthly` |
| AI calls fail with "model not found" | A model id was retired or renamed | Update the model id in `engine/config/tasks.yaml` (Appendix C), run `nlead eval --subset 20`, commit. Fallbacks keep the night running meanwhile |
| Leads look duplicated in the app | Entity resolution missed a match (different names, no shared domain or phone) | Merge them in the app (admin action "Merge into") and add a test case to `resolve.py` tests |
| Messages look too similar to each other | Same angle and segment, low variety | The similarity check should catch it; lower the threshold or add angle variety in the segment YAML |
| Grounded search stops returning results | Free 5,000 monthly queries used up | Wait for the next month or raise the budget; the engine skips grounded search when the monthly count reaches 5,000 |

## 22.6 Done when
- [ ] `docs/runbook.md` contains 22.1 to 22.5 and the founder has read the daily routine once with the builder.
- [ ] Every row of the troubleshooting table has been tested on dev at least once where it can be simulated (paused database, blocked source, retired model id, quota hit).

---

---

# Step 23: Expansion playbook (new domain or country)

**Goal:** add a new segment (a domain in a country) safely, with the same quality bar as wave 1.

**Order of expansion (from A.2.1):**
1. Wave 1 (build): India + UAE, for clinics, real estate and education.
2. Wave 1 widening: the other domains in India and UAE (D2C, hospitality and travel, auto, insurance and loans, gym, salon and spa chains, firms and startups).
3. Wave 2: Saudi Arabia, Qatar, UK, Singapore.
4. Wave 3: US, Australia.

## 23.1 The checklist (one new segment)
1. **Desk research (2 to 4 hours).** Write the answers in `docs/segments-guide.md` under the new segment:
   1. Where do these businesses list themselves? (maps coverage, official registries, directories)
   2. Where do they post jobs? (Check each job board's robots.txt and terms. Prefer official APIs.)
   3. What do they spend money on to get customers? (ads, portals, listings)
   4. Which channel do owners answer: WhatsApp, email, phone?
   5. What does "can pay ₹50K+" (or the local equivalent) look like here? (branches, staff, price points)
   6. Which big chains, platforms and agencies must be excluded?
2. **Maps coverage check.** Run `nlead universe --segment <id> --limit 200 --dry-run` for one city. Compare the Overture and Places counts with a rough real number (for example a registry total). Note gaps.
3. **Official sources first.** Examples to evaluate:

| Country | Official or open sources to check first |
|---|---|
| UAE | Dubai Health Authority facility lists, DLD broker registry, KHDA education lists (verify access at build) |
| Saudi Arabia | Ministry of Commerce business lookup, health facility lists (verify) |
| Qatar | Ministry of Commerce and Industry registry (verify) |
| UK | Companies House API (free, official), CQC register for clinics (free API), Ofsted for education providers |
| Singapore | ACRA business data (check terms and cost), MOH healthcare institution lists |
| US | NPPES NPI Registry API for clinics (free, official), state business registries |
| Australia | ABN Lookup web services (free with registration), AHPRA practitioner register |

4. **Write the segment YAML** (Step 3 format): cities with bounding boxes, categories, registries, job keywords, signal weights, can-pay proxies, exclusions, outreach channel, packaged outcome name, compliance notes, daily quota.
5. **Adapters.** If an official source is worth it, write one adapter (Step 5 pattern, with fixtures and tests).
6. **Signals.** Map local signals to A.12.3 types. Do not invent new types unless needed; if needed, add them to A.12.3, Step 2 and Step 11 together.
7. **Packaged outcome and messages.** Name the outcome (A.2.2 table style). Write 3 example messages per pitch mode in the approved voice (A.2.3). For English-speaking countries keep the same voice; for Arabic-speaking markets keep messages in English unless the founder decides otherwise.
8. **Compliance.** Fill the country row in Step 18.4 and get a short legal check for wave 2 and wave 3 countries. Set `outreach_channel` to `email` where WhatsApp cold messages are risky.
9. **Golden labels.** Label 20 businesses for the new segment (10 good, 10 bad).
10. **Eval.** Run `nlead eval --segment <id>`. Thresholds from Step 17.4.2 apply.
11. **Dry run.** `nlead run night --segment <id> --limit 30 --env dev` and `nlead run morning ...`. The founder reviews 20 leads.
12. **Enable with a small quota.** Set `daily_quota = 30` for 2 weeks.
13. **Review after 100 contacts.** Use the weekly report decision labels (Step 16.2.4): scale, keep or cut.

## 23.2 Domain notes for wave 1 widening (India and UAE)
| Domain | Where they are | Signals that work | Can-pay proxies |
|---|---|---|---|
| D2C and e-commerce | Their own stores (detect Shopify, WooCommerce), Overture shopping categories | Hiring support or operations staff; reviews about delivery or support; no WhatsApp support | Store size, ads running, number of products, price points |
| Hospitality and travel | Places and Overture (hotels, travel agents) | Hiring reservation or sales staff; reviews about slow replies | Rooms or branches, rating count, price per night |
| Auto dealers and service centres | Brand dealer locators (check terms), Places | Hiring telecallers or service advisors; reviews about service follow-up | Brand, branches, workshop size |
| Insurance and loan distributors | Overture and Places categories; regulator agent lists where public | Hiring telecallers; public asks | Team size, branches |
| Gym, salon and spa chains | Places and Overture | Hiring front desk; reviews about booking | Branches, membership price points |
| Firms and startups | Funding news (money proof), job posts for builders, public asks | `hiring_builder`, `public_ask`, `funding` | Funding, team size |

## 23.3 Done when (per new segment)
- [ ] Desk research written in `docs/segments-guide.md`.
- [ ] Segment YAML validates and has compliance notes and an outreach channel.
- [ ] 20 golden labels; eval passes.
- [ ] Dry run reviewed by the founder.
- [ ] Enabled at 30 a day; review scheduled after 100 contacts.

---

---

# Step 24: Timeline and milestones

**Assumption:** one full-time builder (with Claude Code helping), the founder available for decisions and about 4 hours of labelling and review in total. The web app work starts now, as the founder asked, and runs in parallel with the engine from week 1.

## 24.1 Week by week
| Week | Engine | Web app | Founder |
|---|---|---|---|
| Week 0 (now, 2 to 3 days) | Step 0 accounts and keys; Step 1 repo skeleton; Step 2 schema on dev | Next.js skeleton, Nument kit tokens and fonts, email + password login, protected layout | Create accounts (GitHub, Supabase, Render), share keys safely, rotate old keys (18.7.5) |
| Week 1 | Step 3 segments; Step 4 AI router (Gemini only today, see 24.3); Step 5 Overture + Places + ART registry; data check on one Indian and one UAE city | Leads list (reading seed data), lead page (read only), roles and RLS | Review the data check numbers |
| Week 2 | Step 5 remaining wave-1 sources; Steps 6 to 8 (universe, entity resolution, signals, pre-filter) | Today page, stage changes, notes, one-tap WhatsApp links, Do not contact | |
| Week 3 | Steps 9 to 12 (research, extraction batch, verify, score, judge, message) | Pipeline board, engine control page, insights skeleton, golden labelling view | Label the golden set (about 2 hours) |
| Week 4 | Step 13 sheet two-way sync; Step 14 GitHub Actions; Step 17 tests and eval gate; Step 19 cost controls; Step 20 legacy import | Insights with real numbers, settings (users, suppression), inbox, deploy to Render | Try the app daily; send feedback |
| Week 5 | Step 21 dry runs (2 nights), golden eval, cutover | Polish from founder feedback; mobile layout check | Review 20 leads per dry run; approve cutover |
| Week 6 | Ramp 100 to 200 to 300 a day; Step 16 learning (first weekly report); fixes | Report page, audit queue | Daily sending; first weekly review |

## 24.2 Milestones and acceptance
| Milestone | When | Accepted when |
|---|---|---|
| M0 Foundations | End of week 0 | Repo builds; dev database has the full schema; founder can log in to the web app on localhost |
| M1 Data check | End of week 1 | Counts of businesses per city for one Indian and one UAE city are recorded; Places and Overture both work; AI router passes its tests with Gemini |
| M2 Universe and signals | End of week 2 | `nlead universe`, `signals`, `prefilter` run on dev for all 6 wave-1 segments; the app lists real businesses |
| M3 Leads on dev | End of week 3 | A full dry night on dev produces graded leads with verified facts and messages; golden set labelled |
| M4 Automated | End of week 4 | Scheduled runs on dev; sheet and app stay in sync both ways; CI with eval gate is green; legacy data imported to dev |
| M5 Live | End of week 5 | Cutover done (Step 21.3); first prod leads by 07:30 |
| M6 Full volume | End of week 6 | 300 researched a day under ₹750; quality targets in A.1.5 met; first weekly report delivered |

## 24.3 Gemini-only start (OpenAI is unavailable today)
- `settings.providers_enabled = {"gemini": true, "openai": false}` on dev and prod until the founder adds a working OpenAI key.
- Every task in `tasks.yaml` (Appendix C) has a `primary` and `fallbacks`. Gemini can run every task on its own. When OpenAI is disabled, the router skips it and uses the first enabled fallback, logging `provider_fallback` in the run stats.
- When the OpenAI key works, the founder flips `openai` to `true` on the Engine page. Run `nlead eval --subset 20` before and after, and keep whichever is better for `write_message`.
- **Local testing uses only the Gemini key** with a small spend guard: in local and dev runs, set `daily_cap_inr = 100` in the dev `settings` table and always pass `--limit 10` (or less) for commands that call AI. The budget guard (Step 19) stops calls at ₹100.

## 24.4 Effort estimate
| Area | Hours |
|---|---|
| Steps 0 to 2 (setup, skeleton, database) | 20 to 25 |
| Steps 3 to 5 (segments, AI router, sources) | 40 to 50 |
| Steps 6 to 12 (pipeline) | 50 to 60 |
| Step 13 and 14 (sheet sync, Actions) | 15 to 20 |
| Step 15 (web app) | 60 to 80 |
| Steps 16 and 17 (learning, tests, evals) | 25 to 30 |
| Steps 18 to 21 (compliance, costs, migration, go-live) | 15 to 20 |
| Documentation and runbook | 8 to 10 |
| **Total** | **about 230 to 295 hours** (5 to 6 weeks full time for one person; about 3 to 4 weeks with two people, one on the engine and one on the web app) |

## 24.5 Done when
- [ ] M0 to M6 accepted in order, each recorded with a date in the change log (Appendix H).

---

---

# Appendices

## Appendix A: Prompt texts

All prompts live in `engine/prompts/<task>.md`. Each file has front matter, a system part and a user template (Jinja2). The output is always JSON validated against a pydantic model in `engine/src/nument_engine/models.py` (the model names below). Prompts must work the same on Gemini and OpenAI (no provider-specific tricks), because every task can fall back to Gemini (Appendix C).

Common rules included in every prompt's system part:
```
- Use only the information given to you below. Do not use outside knowledge about this business.
- If something is not in the input, return null or "unknown". Never guess.
- Every fact you return must include the exact quote from the input text and the URL it came from.
- Return only JSON that matches the schema. No extra text.
```

### A.1 `classify_signal.md`
```markdown
---
task: classify_signal
version: 1
output: SignalClassification
---
SYSTEM:
You read one job post or one short text about a business and decide what kind of buying signal it is
for an AI and software studio that builds websites, apps, AI assistants and automation.
{{ common_rules }}

Signal types:
- hiring_builder: they are hiring a developer, automation, AI or tech person to build something.
- hiring_frontdesk: they are hiring a receptionist, telecaller, front office, patient coordinator,
  admissions counsellor, customer support or sales executive to handle enquiries.
- public_ask: they publicly ask for a vendor, agency, developer or partner.
- tender: an official request for proposals for software, website or automation.
- none: none of the above.
Also decide if the poster is itself an agency, IT company, staffing firm or software vendor (a competitor).

USER:
Segment: {{ segment_id }} ({{ domain }}, {{ country }})
Source: {{ source }}  URL: {{ url }}  Posted: {{ posted_date or "unknown" }}
Text:
"""{{ text }}"""
Return: {"signal_type": ..., "is_competitor": true|false, "employer_name": ..., "role_title": ...,
"what_they_need": "<one plain sentence>", "quote": "<exact quote that proves the type>", "url": "{{ url }}",
"confidence": 0.0-1.0}
```

### A.2 `classify_news.md`
```markdown
---
task: classify_news
version: 1
output: NewsClassification
---
SYSTEM:
You read one news article and decide whether it reports a growth event for a specific small or medium business
in the segment: a new clinic, new branch, launch, expansion, award, or funding.
Ignore large corporates, hospital chains, government bodies and listed companies.
{{ common_rules }}

USER:
Segment: {{ segment_id }}  Article URL: {{ url }}  Published: {{ published }}
Title: {{ title }}
Text:
"""{{ text }}"""
Return: {"is_relevant": true|false, "event": "new_place|new_branch|news|funding|none",
"business_name": ..., "city": ..., "quote": "...", "url": "{{ url }}", "confidence": 0.0-1.0}
```

### A.3 `classify_page_change.md`
```markdown
---
task: classify_page_change
version: 1
output: PageChangeClassification
---
SYSTEM:
You compare the old and new text of a business's careers or locations page and say what changed.
{{ common_rules }}

USER:
Business: {{ business_name }}  Page: {{ url }}
Old text (fetched {{ old_date }}):
"""{{ old_text }}"""
New text (fetched {{ new_date }}):
"""{{ new_text }}"""
Return: {"change": "new_job|new_branch|removed_job|other|none",
"items": [{"what": "<job title or branch name>", "signal_type": "hiring_builder|hiring_frontdesk|new_branch|none",
"quote": "<exact quote from the NEW text>"}], "url": "{{ url }}"}
```

### A.4 `extract_facts.md`
```markdown
---
task: extract_facts
version: 1
output: FactsExtraction
---
SYSTEM:
You read pages from one business's own website (and its directory profile if given) and extract facts
that help decide whether it can pay for, and needs, AI automation, and who decides.
{{ common_rules }}
- Quotes must be copied exactly, 5 to 40 words, from the page text given. Do not fix spelling.
- Phones: only numbers printed on these pages. Mark the label printed next to them.
- Decision makers: owners, founders, directors, managing partners, medical directors. Not general staff.
- If the business looks like an agency, IT company or software vendor, say so with a quote.

USER:
Segment: {{ segment_id }}  Business: {{ business_name }}  Website: {{ website }}
Structured data found (JSON-LD): {{ structured_data | tojson }}
Tech detected on the site: {{ tech_flags | tojson }}
Pages:
{% for p in pages %}
=== PAGE {{ loop.index }}: {{ p.url }} ===
{{ p.text }}
{% endfor %}
Return JSON with these fields (each fact has value, quote, url):
- business_name
- decision_makers: [{name, role, quote, url}]
- phones: [{number, label, quote, url}]
- emails: [{email, quote, url}]
- branches_count {value, quote, url}
- staff_or_doctors_count {value, quote, url}
- services: [{value, quote, url}]   (max 8)
- price_points: [{item, price, currency, quote, url}]
- booking_method {value: online_widget|whatsapp|phone|form|none|unknown, quote, url}
- whatsapp_present {value: true|false, quote, url}
- chat_widget {value: true|false, quote, url}
- careers_open_roles: [{title, quote, url}]
- has_in_house_tech {value: yes|no|unknown, quote, url}
- is_agency_or_vendor {value: true|false, quote, url}
- languages: [..]
- notes: "<max 2 plain sentences about anything else relevant to selling AI automation, with quote>"
```

### A.5 `verify_flagged.md`
```markdown
---
task: verify_flagged
version: 1
output: FlaggedVerification
---
SYSTEM:
Some facts about a business conflict or could not be matched exactly. Decide for each one whether
the page text supports it. You may only answer from the page text given.
{{ common_rules }}

USER:
Business: {{ business_name }}
Flagged facts:
{% for f in facts %}- id {{ f.id }}: {{ f.field }} = {{ f.value | tojson }} (quote: "{{ f.quote }}", url: {{ f.url }}){% endfor %}
Page texts:
{% for p in pages %}=== {{ p.url }} ===
{{ p.text }}
{% endfor %}
Return: {"results": [{"fact_id": ..., "supported": true|false, "correct_value": <value or null>,
"quote": "<exact supporting quote or empty>", "reason": "<one short sentence>"}]}
```

### A.6 `judge_lead.md`
```markdown
---
task: judge_lead
version: 1
output: LeadJudgement
---
SYSTEM:
You are a careful sales analyst for Nument, an AI-first software studio that sells custom AI automation,
websites and apps to owner-led businesses that can pay at least ₹50,000 (or the local equivalent).
You review one scored business and may adjust its grade by at most ONE step (for example B to A, or B to C).
You must base every statement on the verified facts and signals listed, and cite their ids.
{{ common_rules }}
Grade meanings: A = contact today, strong need and can pay; B = good lead; C = wait for a new signal; D = drop.
Downgrade for: big corporate or chain, agency or vendor, in-house tech team, no real need, cannot reach.
Pick the single best angle for the first message from: {{ allowed_angles | join(", ") }}.

USER:
Segment: {{ segment_id }}  Pitch mode: {{ pitch_mode }}
Score: total {{ total }} (fit {{ fit }}, can-pay {{ can_pay }}, intent {{ intent }}, reach {{ reach }}), grade {{ grade }}
Verified facts:
{% for f in facts %}- [F{{ f.id }}] {{ f.field }}: {{ f.value | tojson }} ("{{ f.quote }}")
{% endfor %}
Active signals:
{% for s in signals %}- [S{{ s.id }}] {{ s.type }} ({{ s.age_days }} days old): {{ s.quote or s.details | tojson }}
{% endfor %}
Return: {"grade": "A|B|C|D", "change": "up|down|same", "note": "<max 2 plain sentences: why this lead, cite ids>",
"angle": "...", "risks": ["..."], "cited_ids": ["F..","S.."], "confidence": 0.0-1.0}
```

### A.7 `write_message.md`
```markdown
---
task: write_message
version: 1
output: MessageDraft
---
SYSTEM:
You write the FIRST WhatsApp message from Nument to one business owner. It must read like a real person texting.
Voice rules (approved by the founder):
- Start: "Hi <first name or Dr. Surname or Mr. Surname>," then say where we saw them in everyday words,
  for example "saw Calmveda's post on Internshala about Claude agents for Amazon and Tally."
  If no person name is verified, start "Hi," and name the business.
- Then one honest line about us, varied, for example "We're Nument, a small dev team, and we build this kind of thing."
- Then ONE idea in plain words, said the way you would say it out loud, specific to them.
- End with ONE short, natural question. Vary it. Examples: "Still looking for someone on this?",
  "Is the search still open?", "Has the role been filled yet?", "Worth a look?"
- 30 to 60 words. Simple English. Contractions are good.
- Never: links, emojis, dashes, prices, "reaching out", "businesses like yours", "AI-powered", "cutting-edge",
  "hope you're well", "Greetings", lists of three, consultant words like "leverage" or "synergy".
- Do not introduce the sender by name (WhatsApp shows "{{ associate_name }}").
- Use only the verified facts and signals given. Every specific detail must come from them.
Pitch mode rules:
- stated_need: they said what they need. Offer to solve exactly that need, as an agency.
- visible_pain: they did not ask, but evidence shows a problem. Name the problem gently using the evidence,
  then offer the packaged outcome: {{ packaged_outcome_name }} ("every enquiry answered in seconds, followed up until it books").
- fit_only: no signal. Be brief, ask a light question about how they handle enquiries today.
Also write an alternate message with a different angle, and two follow-ups (day 3 adds one new useful point,
day 7 is a polite close such as "Shall I close this for now?").

USER:
Segment: {{ segment_id }}  Pitch mode: {{ pitch_mode }}  Angle: {{ angle }}
Business: {{ business_name }}  Person: {{ person_name or "unknown" }} ({{ person_role or "unknown" }})
Where we saw them: {{ seen_where }}
Verified facts:
{% for f in facts %}- [F{{ f.id }}] {{ f.field }}: {{ f.value | tojson }}
{% endfor %}
Signals:
{% for s in signals %}- [S{{ s.id }}] {{ s.type }}: {{ s.summary }}
{% endfor %}
Return: {"message": "...", "message_alt": "...", "followup_d3": "...", "followup_d7": "...",
"facts_used": ["F..","S.."], "angle": "{{ angle }}"}
```

### A.8 `check_message.md`
```markdown
---
task: check_message
version: 1
output: MessageCheck
---
SYSTEM:
You are a strict reviewer of a first WhatsApp message. Score it 0 to 10 with this rubric:
personal detail (2), relevance of the idea (2), easy to reply (2), length and clarity (1), tone (1),
every claim supported by the listed facts (2). Flag anything that sounds like a bot or a brochure.
Rules the message must follow are the same voice rules as the writer (30 to 60 words, no links, emojis, dashes,
prices, banned phrases; exactly one question).

USER:
Message:
"""{{ message }}"""
Facts it may use:
{% for f in facts %}- [F{{ f.id }}] {{ f.field }}: {{ f.value | tojson }}
{% endfor %}
Return: {"score": 0-10, "problems": ["..."], "unsupported_claims": ["<sentence>"], "sounds_like_bot": true|false,
"suggested_fix": "<rewritten message or empty if score >= 9>"}
```

### A.9 `grounded_public_asks.md` (task `grounded_search`)
```markdown
---
task: grounded_search
version: 1
output: PublicAskResults
---
SYSTEM:
Use web search to find PUBLIC posts from the last {{ days }} days where a business in {{ country }} asks for
a developer, agency, automation partner, chatbot or WhatsApp automation for a {{ domain }} business.
Only report posts with a clear ask and a date. Prefer the business's own name and city.
Do not open LinkedIn, X or Instagram pages yourself; you may report what the search results show, with the link.

USER:
Search ideas: {{ queries | join(" | ") }}
Return: {"results": [{"business_name": ..., "city": ..., "ask": "<one sentence>", "quote": "<from the result>",
"url": ..., "posted": "<date or unknown>", "confidence": 0.0-1.0}]}
```
Grounded search is also used for one decision-maker lookup per A lead: same prompt file, section `decision_maker`, asking "Who owns or runs <business>, <city>?" and returning name, role, quote, url.

### A.10 `weekly_audit.md`
```markdown
---
task: weekly_audit
version: 1
output: AuditResult
---
SYSTEM:
You audit one lead the engine produced last week. Be stricter than the original judge.
Check: is it the right segment, can it pay, is the need real and recent, is the contact right,
and is every claim in the message supported by the fresh page text. {{ common_rules }}

USER:
Lead: {{ business_name }} ({{ segment_id }}), grade {{ grade }}, pitch mode {{ pitch_mode }}
Message sent or ready: """{{ message }}"""
Stored facts: {% for f in facts %}[F{{ f.id }}] {{ f.field }}: {{ f.value | tojson }}; {% endfor %}
Fresh page texts: {% for p in pages %}=== {{ p.url }} === {{ p.text }} {% endfor %}
Return: {"audit_grade": "A|B|C|D", "agrees": true|false, "stale_facts": ["F.."], "phone_still_present": true|false,
"message_claims_ok": true|false, "notes": "<max 2 sentences>"}
```

## Appendix B: `engine/config/prices.yaml`

> **Verify at build.** These prices come from public trackers and Google's docs as of 12 Nov 2026. Model names and prices change often. Check the official pricing pages and update this file before go-live and every month (Step 22.3).

```yaml
verified_on: 2026-11-12
fx_inr_per_usd: 88          # runtime value lives in settings.fx_inr_per_usd
batch_discount: 0.5         # Gemini and OpenAI batch APIs: about half price

models:                     # USD per 1M tokens
  gemini-3.1-pro:        {provider: gemini, input: 2.00, output: 12.00, note: "prompts over 200K tokens cost more"}
  gemini-3-flash:        {provider: gemini, input: 0.50, output: 3.00}
  gemini-3.1-flash-lite: {provider: gemini, input: 0.25, output: 1.50}
  gpt-5.4:               {provider: openai, input: 2.50, output: 15.00}
  gpt-5-mini:            {provider: openai, input: 0.25, output: 2.00}
  gpt-5-nano:            {provider: openai, input: 0.05, output: 0.40}

search:
  gemini_grounding:  {free_per_month: 5000, usd_per_1000_after: 14.00, note: "billed per search query the model runs"}
  openai_web_search: {usd_per_1000_calls: 10.00, note: "plus search content tokens at the model's input price"}

google_places:              # India pricing page (verify which pricing your billing account gets)
  india:
    text_search_ids_only:      {usd_per_1000: 0.00, free_per_month: unlimited}
    place_details_pro:         {usd_per_1000: 5.10, free_per_month: 35000}
    place_details_enterprise:  {usd_per_1000: 6.00, free_per_month: 7000}
    place_details_enterprise_atmosphere: {usd_per_1000: 7.50, free_per_month: 7000}
  global:                   # verify: free caps are much smaller outside India
    place_details_enterprise:  {usd_per_1000: null, free_per_month: 1000}
    place_details_enterprise_atmosphere: {usd_per_1000: null, free_per_month: 1000}

pagespeed_insights: {usd_per_1000: 0.00, note: "free; key recommended; verify daily quota"}
```

## Appendix C: `engine/config/tasks.yaml` (Balanced tier, with fallbacks)

**Rule (founder, 12 Nov 2026):** OpenAI is unavailable for now. Every task has a `primary` and `fallbacks`, and **Gemini can run every task alone**. The router reads `settings.providers_enabled` (runtime) and skips disabled providers.

Router behaviour (Step 4 implements it):
1. Build the candidate list: `[primary] + fallbacks`, keep only entries whose provider is enabled in `settings.providers_enabled` and not marked unhealthy in this run.
2. Try the first candidate. On a timeout or server error after `max_retries`, move to the next candidate.
3. On a JSON schema failure, retry the same model once with the validation error added to the prompt, then move to the next candidate.
4. If the task is `mode: batch` and batch submission fails, the morning run falls back to `mode: sync` for the items that are due (counts toward the cap).
5. Log every fallback in the run stats as `provider_fallback` with task and reason.
6. Budget priority (Step 19): `essential` tasks run until 100% of the cap; `important` stop at 90%; `optional` stop at 80%.

```yaml
tier: balanced
providers_enabled_default: {gemini: true, openai: false}   # seed for settings.providers_enabled; app can change it
defaults: {timeout_s: 120, max_retries: 2, temperature: 0.2}

tasks:
  classify_signal:
    priority: important
    mode: sync
    primary:   {provider: gemini, model: gemini-3.1-flash-lite}
    fallbacks: [{provider: gemini, model: gemini-3-flash}, {provider: openai, model: gpt-5-nano}]
    max_input_tokens: 3000
    max_output_tokens: 400
    temperature: 0
    schema: SignalClassification
    prompt: prompts/classify_signal.md

  classify_news:
    priority: optional
    mode: sync
    primary:   {provider: gemini, model: gemini-3.1-flash-lite}
    fallbacks: [{provider: gemini, model: gemini-3-flash}, {provider: openai, model: gpt-5-nano}]
    max_input_tokens: 4000
    max_output_tokens: 300
    temperature: 0
    schema: NewsClassification
    prompt: prompts/classify_news.md

  classify_page_change:
    priority: important
    mode: sync
    primary:   {provider: gemini, model: gemini-3.1-flash-lite}
    fallbacks: [{provider: gemini, model: gemini-3-flash}, {provider: openai, model: gpt-5-nano}]
    max_input_tokens: 6000
    max_output_tokens: 500
    temperature: 0
    schema: PageChangeClassification
    prompt: prompts/classify_page_change.md

  extract_facts:
    priority: essential
    mode: batch                 # submitted at night, collected in the morning
    primary:   {provider: gemini, model: gemini-3-flash, thinking: low}
    fallbacks: [{provider: gemini, model: gemini-3.1-pro, thinking: low}, {provider: openai, model: gpt-5-mini}]
    max_input_tokens: 16000
    max_output_tokens: 2000
    temperature: 0
    schema: FactsExtraction
    prompt: prompts/extract_facts.md

  verify_flagged:
    priority: important
    mode: sync
    primary:   {provider: gemini, model: gemini-3-flash}
    fallbacks: [{provider: gemini, model: gemini-3.1-pro}, {provider: openai, model: gpt-5-mini}]
    max_input_tokens: 6000
    max_output_tokens: 600
    temperature: 0
    schema: FlaggedVerification
    prompt: prompts/verify_flagged.md

  judge_lead:
    priority: important
    mode: sync
    top_fraction: 0.5           # only the best half after rule scoring
    primary:   {provider: gemini, model: gemini-3.1-pro}
    fallbacks: [{provider: gemini, model: gemini-3-flash}, {provider: openai, model: gpt-5.4}]
    max_input_tokens: 6000
    max_output_tokens: 1000
    temperature: 0.1
    schema: LeadJudgement
    prompt: prompts/judge_lead.md

  write_message:
    priority: essential
    mode: sync
    primary:   {provider: openai, model: gpt-5-mini}           # skipped while OpenAI is disabled
    fallbacks: [{provider: gemini, model: gemini-3-flash}, {provider: gemini, model: gemini-3.1-pro}]
    max_input_tokens: 3000
    max_output_tokens: 700
    temperature: 0.7
    schema: MessageDraft
    prompt: prompts/write_message.md

  check_message:
    priority: important
    mode: sync
    primary:   {provider: gemini, model: gemini-3-flash}
    fallbacks: [{provider: gemini, model: gemini-3.1-flash-lite}, {provider: openai, model: gpt-5-mini}]
    max_input_tokens: 3000
    max_output_tokens: 400
    temperature: 0
    schema: MessageCheck
    prompt: prompts/check_message.md

  grounded_search:
    priority: optional
    mode: sync
    daily_limit: 160            # keeps inside 5,000 free queries a month
    primary:   {provider: gemini, model: gemini-3-flash, tools: [google_search]}
    fallbacks: [{provider: openai, model: gpt-5-mini, tools: [web_search]}]
    max_input_tokens: 1500
    max_output_tokens: 800
    temperature: 0
    schema: PublicAskResults
    prompt: prompts/grounded_public_asks.md

  weekly_audit:
    priority: optional
    mode: sync
    weekly_limit: 20
    primary:   {provider: gemini, model: gemini-3.1-pro}
    fallbacks: [{provider: gemini, model: gemini-3-flash}, {provider: openai, model: gpt-5.4}]
    max_input_tokens: 8000
    max_output_tokens: 800
    temperature: 0
    schema: AuditResult
    prompt: prompts/weekly_audit.md
```
Note: grounded search falls back only to OpenAI web search. While OpenAI is disabled, when the Gemini grounding quota or budget runs out the task is simply skipped for the day (it is optional).

## Appendix D: `engine/config/exclusions.yaml` (starter list)

> Starter list only. Extend it from the weekly report's suggestions (Step 16.5). Matching is case-insensitive on the business name (contains) or the web domain (exact registrable domain). A match sets `businesses.status = 'rejected'` with `reject_reason = 'excluded:<reason>'`.

```yaml
version: 1
rules:
  # Hospital groups and big healthcare chains (India and UAE)
  - {reason: hospital_or_chain, segments: [clinics-in, clinics-ae], names: [
      "apollo hospitals", "apollo clinic", "apollo cradle", "apollo fertility", "fortis", "max healthcare",
      "manipal hospital", "narayana health", "medanta", "aster dm", "aster clinic", "aster hospital",
      "cloudnine", "motherhood hospital", "rainbow children", "nmc healthcare", "mediclinic",
      "cleveland clinic abu dhabi", "king's college hospital", "american hospital dubai", "burjeel",
      "thumbay", "prime hospital", "saudi german hospital"]}
  # Large franchise or corporate clinic chains
  - {reason: corporate_chain, segments: [clinics-in, clinics-ae], names: [
      "kaya skin clinic", "kaya clinic", "vlcc", "oliva skin", "kolors", "dr batra", "clove dental",
      "sabka dentist", "indira ivf", "nova ivf", "birla fertility", "ferty9", "oasis fertility", "milann"]}
  # Big developers and property portals (portals are not buyers)
  - {reason: corporate_or_portal, segments: [realestate-in, realestate-ae], names: [
      "dlf", "godrej properties", "lodha", "macrotech", "prestige group", "sobha", "brigade group",
      "tata housing", "mahindra lifespaces", "oberoi realty", "puravankara", "nobroker", "housing.com",
      "99acres", "magicbricks", "square yards", "anarock", "jll", "cbre", "knight frank", "colliers",
      "emaar", "damac", "nakheel", "meraas", "aldar", "bayut", "property finder", "dubizzle"]}
  # Large education companies
  - {reason: corporate, segments: [education-in, education-ae], names: [
      "byju", "unacademy", "physicswallah", "physics wallah", "allen career", "aakash", "fiitjee",
      "vedantu", "upgrad", "leverage edu", "idp education", "leap scholar", "yocket",
      "gems education", "taaleem", "aldar education"]}
  # Software vendors and platforms in our space (competitors, not buyers)
  - {reason: vendor, segments: ["*"], names: [
      "practo", "interakt", "aisensy", "gallabox", "wati", "leadsquared", "zoho", "freshworks",
      "haptik", "yellow.ai", "gupshup", "kaleyra", "exotel", "knowlarity"]}
  # Agencies and IT service firms (pattern rules; also caught by the is_agency_or_vendor fact)
  - {reason: agency, segments: ["*"], name_patterns: [
      "\\b(digital marketing|web solutions|software solutions|it services|infotech|technologies pvt)\\b",
      "\\b(web design|app development|seo services|marketing agency)\\b"]}
```

## Appendix E: Stages and colours
See A.12.2. The app (Step 15) and the sheet (Step 13) both use that table. Do not define stage colours anywhere else.

## Appendix F: Verify-at-build list
Check each item on the day you build the step that uses it, and write the answer and date in `docs/segments-guide.md` or the relevant config file.

| # | Item | Why it matters | Where to check | Step |
|---|---|---|---|---|
| 1 | Overture taxonomy codes for real estate and education (for example agents, developers, tutoring, test preparation, educational consultants) | Wrong codes mean missing businesses | Overture taxonomy explorer and `taxonomy.csv` for the current release | 3, 5 |
| 2 | Overture current release path and that `taxonomy` replaced `categories` | Monthly refresh breaks if the path changes | Overture STAC catalog and release notes | 5 |
| 3 | UAE registries: Dubai Health Authority facility lists, DLD broker registry, KHDA lists: public access, terms, any CAPTCHA | Better UAE coverage | Each authority's website | 5, 23 |
| 4 | Adzuna API coverage for India and UAE job ads | Official job source option | Adzuna developer docs | 5 |
| 5 | Practo terms of use on automated access to profile pages | We only read allowed profile pages slowly; confirm terms | practo.com terms page | 5, 18 |
| 6 | Apna terms and robots status | Grey source; confirm still reachable and rules unchanged | apna.co robots.txt and terms | 5, 18 |
| 7 | Gemini model ids available on the founder's key (run `client.models.list()`), batch API support, grounding price for the chosen model | Router config must match real ids | Google AI Studio and Gemini API docs | 4, Appendix C |
| 8 | OpenAI key working and model ids (`gpt-5-mini`, `gpt-5-nano`, `gpt-5.4`), batch and web search prices | OpenAI is disabled today; check when the founder enables it | OpenAI platform docs and pricing | 4, Appendix C |
| 9 | All prices in Appendix B | Budget guard accuracy | Official pricing pages | 19 |
| 10 | Google Places India free caps per SKU, and which pricing the billing account gets | Places cost stays ₹0 only inside caps | Google Maps Platform India pricing page | 5, 19 |
| 11 | Render free tier sleep rules and Starter price | Cold starts vs about $7 a month | render.com pricing | 15 |
| 12 | GitHub Actions free minutes for private repos and schedule behaviour | The 2,000-minute budget | GitHub billing docs | 14 |
| 13 | Supabase free tier limits (database size, pause after inactivity, projects per account, region Mumbai) | Avoid surprise pauses | Supabase pricing and docs | 2 |
| 14 | India DPDP Rules breach-notification timeline | Incident response | Official DPDP Rules text | 18 |
| 15 | GDELT terms and DOC API limits | News signals | GDELT docs | 5 |
| 16 | WhatsApp limits for new chats from a business app number | Founder's sending guidance | WhatsApp Business help centre | 18 |
| 17 | Country rules for wave 2 and 3 (Step 18.4 table) | Legal safety | Short legal check | 23 |

## Appendix G: Glossary
See A.5.

## Appendix H: Change log
| Version | Date | Change |
|---|---|---|
| 1.0 | 12 Nov 2026 | First complete plan, agreed with the founder: multi-domain, multi-country targets in waves; pitch decided by the lead's signal; Balanced tier; ₹750 a day cap and up to 300 researched a day; GitHub Actions, Supabase, Render web app with email and password login and the Nument kit; app and sheet both editable with the database as the source of truth |
| 1.0 | 12 Nov 2026 | OpenAI unavailable: every AI task has a primary and fallbacks, Gemini can run every task alone, `settings.providers_enabled` added (OpenAI off), local testing on Gemini only with a ₹100 guard |
| | | Record each milestone (M0 to M6, Step 24.2) here with its date |
