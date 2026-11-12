# Nument Leads

Nument Leads finds businesses that are likely to buy from Nument, proves why with evidence, writes a
personal first message, and has the best leads ready in a web app and a Google Sheet by 07:30 IST every
morning. It runs on its own: a Python engine scheduled by GitHub Actions, a Supabase Postgres database as
the single source of truth, and a Next.js web app on Render.

Nument is an AI-first software studio. The engine looks for owner-led businesses that spend money to win
customers, lose some of them to slow replies and manual work, and can pay ₹50K or more: clinics, real
estate and education first, in India and the UAE, with more domains and countries added as configuration.

The complete build manual, with every decision and contract, is [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Contents

- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Daily operations](#daily-operations)
- [Data and outreach policy](#data-and-outreach-policy)
- [Security](#security)
- [Testing and quality](#testing-and-quality)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

## How it works

| Stage | When | What happens |
|---|---|---|
| 1. Universe | Monthly | Every business in each market from Overture Maps, Google Places and official registries, merged into one record per real company |
| 2. Signals | Nightly, 02:00 IST | Dated evidence of need: job posts for front-desk or builder roles, review complaints, public asks, new branches, news |
| 3. Pre-filter | Nightly | Free rules first: fit, size, exclusions, the suppression list, cool-downs and daily quotas |
| 4. Research | Nightly | Up to 8 pages per business through the polite crawler, then fact extraction in an AI batch |
| 5. Verify | Morning, 06:00 IST | Code finds every quoted fact again in the page text; phones and websites are checked |
| 6. Score and judge | Morning | Fit, can-pay, intent and reach give a 0 to 100 score and a grade from A to D; the top model reviews the best half |
| 7. Message | Morning | A short first message in the approved voice, checked by rules and by a second model |
| 8. Sync | Morning and daytime | The sheet and the app show the same leads; edits in either one flow back to the database |
| 9. Learn | Mondays | Outcomes adjust scoring within strict limits, an audit re-checks recent leads, and a weekly report says what to scale and what to cut |

People stay in charge of everything outside research: the founder opens the app or the sheet, taps once to
open WhatsApp with the message typed, sends it, and marks the stage. The engine never sends a message.

## Architecture

```
                             GitHub Actions
                 schedules (night, morning, sheet, weekly,
                    monthly, backup) and CI with eval gate
                                   |
                                   v
 Public sources -------> Python engine (nlead) -------> AI router
 Overture, Places,       polite HTTP, research,          Gemini runs every task; OpenAI optional;
 registries, job         verify, score, judge,           fallback chains, circuit breakers,
 boards, websites        message, learn                  ₹750 daily cap
                                   |
                                   | service role
                                   v
                       Supabase Postgres (source of truth) <---- signed-in user, RLS ---- Web app
                                   ^                                                     Next.js on Render
                                   | two-way sync, service account                       Today, Leads, Pipeline,
                                   v                                                     Insights, Engine, Settings
                       Google Sheets (master and caller)
```

Principles the code keeps (A.6.3 in the plan):

- The database is the single source of truth; the app and the sheet are views that can edit it.
- Every fact carries the exact quote and the URL it came from, and code re-checks the quote. AI never puts
  an unverified claim in front of the founder.
- Every step is idempotent, so a crashed run is simply run again.
- Cheap before expensive: free rules first, small models next, the top model only on the best half.
- A new market is a new YAML file, not new code.
- Fail safe: a source that blocks us is left alone; at the spend cap, optional work stops first.
- The founder's sheet is rewritten only after a complete, successful build.

## Repository layout

```
.
├── IMPLEMENTATION_PLAN.md   the build manual: decisions, contract (Part A) and Steps 0 to 24
├── engine/                  Python 3.12 engine and the nlead command line
│   ├── src/nument_engine/   cli, settings, db, models, segments, llm, sources, pipeline,
│   │                        research, sheet, learn (metrics, weights, report), ops (health, audit)
│   ├── config/              scoring.yaml, exclusions.yaml, prices.yaml, tasks.yaml
│   ├── segments/            one YAML file per market (domain x country)
│   ├── prompts/             AI prompt files, versioned
│   ├── evals/               golden set and eval harness
│   └── tests/               pytest suite with a throwaway Postgres
├── web/                     Next.js web app (App Router, Supabase Auth, Nument design kit)
├── supabase/                migrations, CLI config and Row Level Security tests
├── docs/                    runbook, data policy, incidents, segments guide
├── .github/                 CI, scheduled workflows and Dependabot
├── .env.example             every environment variable, names only
└── .gitleaks.toml           secret scanning rules
```

## Quick start

### Prerequisites

| Tool | Version | For |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.5 or newer | Python 3.12 and the engine's locked dependencies |
| PostgreSQL binaries | 17 recommended | The test suite starts a throwaway Postgres from them (macOS: `brew install postgresql@17`) |
| Node.js and pnpm | Node 22 LTS or newer | The web app |
| gitleaks | 8.x, optional | Local secret scanning before commits |

You also need access to the Supabase dev project and a Gemini API key. Ask the admin; never share keys in
chat, issues or commit messages.

### Engine

```bash
cd engine
uv sync
cp ../.env.example .env.dev && chmod 600 .env.dev   # fill in the dev values only
uv run nlead db migrate --env dev                  # apply supabase/migrations
uv run nlead db sync-segments --env dev            # copy the segment files into the database
uv run nlead health --env dev                      # no FAIL lines; a WARN line says what is missing
uv run pytest                                      # needs only local PostgreSQL binaries
```

Every command accepts `--env dev|prod`, `--segment ID`, `--limit N` and `--dry-run`. Local testing uses
Gemini only, with small limits: pass `--limit 10` or less to commands that call AI, and keep the dev
`daily_cap_inr` low. More in [engine/README.md](engine/README.md).

### Web app

```bash
cd web
pnpm install
cp ../.env.example .env.local && chmod 600 .env.local   # fill in the web values
pnpm dev                                                 # http://localhost:3000
```

Public sign-up is off. An admin creates every account in the app's settings, and new users change their
password on first login.

## Configuration

Values live in `engine/.env.<env>` and `web/.env.local` locally, and in GitHub and Render secrets in the
cloud. They are never committed; [.env.example](.env.example) lists every name.

| Variable | Used by | Secret |
|---|---|---|
| `APP_ENV` | engine, web | no (`dev` or `prod`) |
| `DATABASE_URL` | engine | yes (Supabase session pooler, port 5432) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | engine, web server | the key is secret, server side only |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_APP_URL` | web browser | no (protected by Row Level Security) |
| `GEMINI_API_KEY`, `GEMINI_API_KEY_BACKUP`, `OPENAI_API_KEY` | engine | yes |
| `GOOGLE_MAPS_API_KEY` | engine | yes (Places API and PageSpeed Insights only) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` (CI) or `GOOGLE_SERVICE_ACCOUNT_FILE` (local) | engine | yes |
| `SHEET_MASTER_ID`, `SHEET_CALLER_ID` (prod), `SHEET_STAGING_ID` (dev) | engine | no |
| `ASSOCIATE_NAME`, `USER_AGENT` | engine | no |
| `GH_REPO`, `GH_DISPATCH_REF`, `GH_DISPATCH_TOKEN` | web server | the token is secret |
| `BACKUP_PASSPHRASE` | engine in CI | yes |
| `ALERT_EMAIL`, `ALERT_EMAIL_FROM`, `RESEND_API_KEY` | engine, optional email | the key is secret |
| `DEV_DATABASE_URL` | CI eval gate | yes |

Two safety rules are built in: dev refuses to start with the live sheet ids, and prod refuses to start
without them.

Switches the founder changes without a deploy live in the `settings` table and on the app's Engine page:
the daily AI budget (`daily_cap_inr`, alert at `alert_pct`), research volume, provider switches
(`providers_enabled`; OpenAI starts off), source and segment kill switches, and per-source daily limits.

## Daily operations

| When | What | Time |
|---|---|---|
| Daily | Engine page: last runs, leads added, spend against the cap, blocked sources; then send from Today | 5 minutes |
| Mondays | Read the weekly report, act on scale and cut, mark the five audit leads, promote thumbed leads to the golden set | 30 minutes |
| Monthly | Universe refresh, prices check, Dependabot, suppression and users review, cost review | 1 hour |
| Quarterly | Rotate keys, test a backup restore, review models with the full eval | Half a day |

`uv run nlead health --env prod` shows the state of every service, source, quota and run. The full routine,
the meaning of every check and the troubleshooting table are in [docs/runbook.md](docs/runbook.md).

## Data and outreach policy

- Public pages and official APIs only. Grey-area pages at a slow rate, obeying robots.txt and stopping when
  blocked.
- Never: logins, fake accounts, CAPTCHA solving, proxies or IP rotation, private APIs, data brokers, guessed
  numbers, or fetching LinkedIn, X, Instagram or Facebook. Search snippets that mention them are allowed.
- Phones only where the business published them: its own website first, its own Google listing as a
  labelled fallback.
- Minimal personal data, opt-outs kept forever, deletion on request within 7 days, and Google Places content
  refreshed or removed within 30 days.
- The engine drafts; people send, one by one, within WhatsApp's limits.

All of it is enforced in code and tested; details, retention periods and country rules are in
[docs/data-policy.md](docs/data-policy.md).

## Security

- Row Level Security on every table. The engine uses the service role; the app uses the signed-in user's
  session. Roles: `admin`, `caller` (no money, no costs, no settings) and `viewer` (read only). Money is only
  readable by admins.
- Secrets stay in GitHub and Render secrets and local env files with permission 600; the service role key
  never reaches the browser.
- gitleaks scans the whole history in CI; `pre-commit install` adds the same check before local commits.
- Logs never print keys, full phone numbers or full emails.
- GitHub Actions are pinned to commit SHAs and Dependabot keeps dependencies current.
- Two-factor authentication on every account; keys rotate quarterly. Incidents follow
  [docs/incidents.md](docs/incidents.md).

## Testing and quality

```bash
cd engine
uv run ruff check . && uv run ruff format --check .
uv run mypy src evals
uv run pytest                 # unit, database, RLS and compliance tests
uv run pytest -m "not live"   # what CI runs: no real APIs
```

The database tests start a throwaway Postgres from the local binaries (or use `NLEAD_TEST_DATABASE_URL`),
apply every migration exactly as production does, and never touch Supabase. Network compliance rules (the
never-fetch list, robots.txt, honest identity, blocks and proxies) and forbidden dependencies have their
own tests.

Lead quality is measured on a golden set of about 100 businesses the founder labelled good or bad, with hand
checked facts for 30 of them. `uv run nlead eval --subset 20 --env dev` scores fact precision, field recall,
phone accuracy, grade precision, bad rejection, message lint, the critic score and unverified claims against
fixed thresholds. See [engine/evals/README.md](engine/evals/README.md).

| CI job | Runs on | Checks |
|---|---|---|
| `engine` | every push and pull request | ruff, formatting, mypy, the full test suite against a Postgres service |
| `secrets` | every push and pull request | gitleaks over the whole history |
| `eval-gate` | pull requests that change prompts, models, prices, scoring, segments, exclusions or the quality stages | the 20-business golden subset on dev; a failed threshold or a budget skip blocks the merge |

The web app has its own unit tests (Vitest) and end-to-end tests (Playwright).

## Deployment

### GitHub Actions

| Workflow | Schedule (IST) | Does |
|---|---|---|
| `ci.yml` | every push and pull request | the checks above |
| `night.yml` | daily 02:00 | health, universe top-up, signals, pre-filter, research, AI batch submission |
| `morning.yml` | daily 06:00 | collect the batch, verify, score, judge, message, sheet sync, summary |
| `sheet-sync.yml` | every 2 hours, 09:00 to 21:00 | pull sheet edits, push changes, catch up late batch items |
| `weekly.yml` | Mondays 07:00 | re-weighting, audit, weekly report |
| `monthly.yml` | the 1st, 22:30 | universe refresh, retention |
| `backup.yml` | Sundays 23:00 | encrypted dump of the public schema |

Secrets and variables live at repository level (GitHub environments need a paid plan on a private personal
repository). Each workflow passes the live sheet ids only to `prod` runs and the staging sheet id only to `dev`
runs, so a dev run can never write a live sheet. Scheduled runs use `prod` and stay off until the repository
variable `SCHEDULES_ENABLED` is `true`. Every workflow can be started by hand from the Actions tab or from the
app's Engine page, with environment, dry run, limit and segment options.

### Supabase

Schema changes are numbered SQL files in `supabase/migrations`. Apply them to dev first, run the tests, then
prod:

```bash
cd engine
uv run nlead db migrate --env dev --dry-run   # list what would be applied
uv run nlead db migrate --env dev
```

The Supabase CLI (`supabase db push`) reads the same history table, so either tool can be used. Never edit
a migration that has been applied; add the next number.

### Render

The web app deploys from `render.yaml` as a Node web service rooted at `web/`, built with pnpm and started as
a standalone Next.js server, with `/api/health` as the health check. Pushes to `main` that change `web/`
redeploy automatically. Public `NEXT_PUBLIC_` values are read at build time, so changing them needs a
redeploy. The free plan sleeps after 15 idle minutes; the Starter plan stays awake.

## Troubleshooting

| Symptom | Where to look |
|---|---|
| No new leads in the morning | Actions tab for `night.yml` and `morning.yml`; `nlead health --env prod` |
| "cannot reach the database" | The Supabase project may be paused; `DATABASE_URL` must be the session pooler (port 5432) |
| `FAIL` in `nlead health` | The check's detail line says what to fix; the runbook explains each check |
| A source is "blocked" | Expected after a 403, 429 or challenge page; it rests 7 days. Never work around it |
| Spend near the cap early | `costs` by task for today; check `engine/config/prices.yaml` |
| The eval gate failed | The job log shows the metric table; run `nlead eval --subset 20 --env dev` locally |
| The sheet and the app disagree | Last `sheet_sync` run and `conflict_overridden` activities; `nlead sheet sync` |

The complete table is in [docs/runbook.md](docs/runbook.md#troubleshooting).

## Documentation

| Document | What it covers |
|---|---|
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | The build manual: decisions, the shared contract, every step |
| [engine/README.md](engine/README.md) | Engine setup, commands, database and tests |
| [engine/evals/README.md](engine/evals/README.md) | The golden set, eval commands, metrics and thresholds |
| [docs/runbook.md](docs/runbook.md) | Daily, weekly, monthly and quarterly routine; health checks; troubleshooting |
| [docs/data-policy.md](docs/data-policy.md) | Sources, enforcement, personal data, retention, country rules, security |
| [docs/incidents.md](docs/incidents.md) | Incident playbook and log |
| [docs/segments-guide.md](docs/segments-guide.md) | How to add a market |

Private repository. Copyright Nument. All rights reserved.
