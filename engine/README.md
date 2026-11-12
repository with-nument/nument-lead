# Nument Leads engine

The engine finds businesses that are likely to buy from Nument, researches them from public sources, scores
them, writes a first message and keeps the web app and the Google Sheets in sync. It is a Python 3.12 package
with one command line tool, `nlead`, run every night by GitHub Actions and by hand from a laptop.

The full build manual is `IMPLEMENTATION_PLAN.md` at the repository root. This README covers how to set up,
run and test the engine.

- [Requirements](#requirements)
- [Setup](#setup)
- [Configuration](#configuration)
- [Commands](#commands)
- [Database](#database)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Rules](#rules)
- [Troubleshooting](#troubleshooting)

## Requirements

| Tool | Version | Why |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.5 or newer | Installs Python 3.12 (pinned in `.python-version`) and every dependency |
| PostgreSQL binaries | 16 or newer, 17 recommended | The tests start a throwaway Postgres from them. Supabase runs 17. macOS: `brew install postgresql@17` |
| Chromium for Playwright | optional | Needed from Step 9 (website research): `uv run playwright install chromium` |

## Setup

```bash
cd engine
uv sync                              # .venv with Python 3.12 and the locked dependencies
cp ../.env.example .env.dev          # then fill in the dev values (see Configuration)
chmod 600 .env.dev
uv run nlead --help
uv run nlead db status --env dev     # checks the connection and lists applied migrations
```

## Configuration

### Environment files
Settings come from `engine/.env.<APP_ENV>` locally and from plain environment variables in CI (environment
variables always win). The full list is A.12.7 in the plan; `../.env.example` has every name with no values.

| Variable | Needed for | Notes |
|---|---|---|
| `APP_ENV` | everything | `dev` or `prod`. `--env` on the command line sets it |
| `DATABASE_URL` | everything | Supabase **session pooler**, port 5432 (IPv4). Never the direct connection or port 6543 |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | storage uploads, admin tasks | Server side only, never in a `NEXT_PUBLIC_` variable |
| `GEMINI_API_KEY`, `GEMINI_API_KEY_BACKUP` | AI tasks (Step 4) | The backup key is used when the first one hits its quota |
| `OPENAI_API_KEY` | AI tasks (Step 4) | OpenAI stays off until `settings.providers_enabled.openai` is switched on |
| `GOOGLE_MAPS_API_KEY` | Places and PageSpeed (Steps 5, 9) | Restricted to those two APIs |
| `GOOGLE_SERVICE_ACCOUNT_FILE` or `GOOGLE_SERVICE_ACCOUNT_JSON` | sheet sync (Step 13) | A file path locally, the JSON text in CI |
| `SHEET_STAGING_ID` | dev sheet sync | Dev writes only to the staging sheet |
| `SHEET_MASTER_ID`, `SHEET_CALLER_ID` | prod sheet sync | **Refused in dev**: the engine will not start with them when `APP_ENV=dev` |
| `ASSOCIATE_NAME`, `USER_AGENT` | messages, polite crawling | Defaults: `Aditya`, `NumentLeadBot/1.0 (+https://nument.in)` |
| `BACKUP_PASSPHRASE` | backups | CI |
| `RESEND_API_KEY` | email (morning list, alerts, weekly report) | Without it nothing is sent. `nlead notify test --to <email>` sends a sample; `nlead notify preview --out <dir>` writes every email as HTML and text |
| `ALERT_EMAIL_FROM`, `ALERT_REPLY_TO`, `APP_URL` | email sender, reply-to and links | Defaults: `Nument Leads <leads@nument.in>`, `heyy.abhigyan@gmail.com`, `https://nument-leads-web.onrender.com`. Empty means the default |
| `ALERT_EMAIL` | email fallback | Gets every email while the `notify_recipients` list (Settings > Email recipients) is empty |

Secrets are typed `SecretStr`, so they never appear in logs, reprs or error messages.

### Runtime settings
Switches the founder changes without a deploy live in the `public.settings` table (seeded by
`supabase/migrations/0004_seed.sql`, edited on the app's Engine page): the daily AI budget (`daily_cap_inr`),
research volume, provider switches (`providers_enabled`), source and segment kill switches and per-source
daily limits.

### Segments
Each market is one YAML file in `segments/` (for example `clinics-in.yaml`), validated on load. Defaults for
scoring are in `config/scoring.yaml`; chains, hospitals, agencies and competitors that are never leads are in
`config/exclusions.yaml`. See `../docs/segments-guide.md` before adding a market.

## Commands

Global flags work on every command, before or after it:

```bash
uv run nlead --env dev --segment clinics-in --limit 20 --dry-run universe
uv run nlead universe --segment clinics-in --limit 20 --dry-run --env dev     # the same
```

| Flag | Meaning |
|---|---|
| `--env dev\|prod` | Which environment file and database to use (default `dev`) |
| `--segment ID` | Only this segment; repeat for more (default: every enabled segment) |
| `--limit N` | At most N items per stage |
| `--dry-run` | No sheet writes, no batch submission, no paid calls |
| `--max-spend-inr X` | Hard cap on paid AI and API calls for this run |
| `--json-logs` / `--pretty-logs` | JSON log lines (default, for CI) or readable console output |

| Command | What it does | Built in |
|---|---|---|
| `nlead universe [--monthly]` | Build or refresh the universe from Overture, Places and registries | Step 6 |
| `nlead signals` | Run every signal watcher | Step 7 |
| `nlead prefilter` | Apply the rules and build today's research queue | Step 8 |
| `nlead research` | Crawl queued businesses, store pages, detect tech | Step 9 |
| `nlead extract submit` / `collect` | Submit or collect the AI fact extraction batch | Step 9 |
| `nlead verify` | Re-check quotes, phones and websites | Step 10 |
| `nlead score` / `nlead judge` | Scores, grades and the top model's second opinion | Step 11 |
| `nlead message` | Write, lint and check messages | Step 12 |
| `nlead sheet sync [--light]` | Pull people's edits, then push both views (`--light` skips Lead details when no lead came or went) | Step 13 |
| `nlead sheet push [--light] [--resort]` / `nlead sheet pull [--seed-snapshots]` | One direction only; `--seed-snapshots` adopts sheets the old engine wrote | Steps 13, 20 |
| `nlead sheet check` / `nlead sheet render --out DIR` | Can the service account open each sheet; export every tab to PDF for a visual check | Step 13 |
| `nlead learn`, `nlead report weekly`, `nlead audit` | Learning loop, weekly report, weekly audit | Steps 16, 17 |
| `nlead eval [--subset N]` | Golden-set evaluation | Step 17 |
| `nlead health` | Check every service, source and quota | Step 22 |
| `nlead backup [--out PATH]` | Encrypted data dump to the private `backups` bucket (restore steps in `ops/backup.py`) | Step 14 |
| `nlead migrate-legacy [--root PATH]` | One-time import from the old `lead-engine` folder; safe to re-run | Step 20 |
| `nlead run night` / `morning` / `sheet [--light]` / `weekly` / `monthly` | Orchestrated runs for GitHub Actions | Step 14 |
| `nlead db migrate` / `status` / `sync-segments` | Apply migrations, list them, copy segment files into the database | ready |

Every pipeline command writes one row in `public.runs` (status `ok`, `partial` or `failed`) and puts the run id
on every log line. A stage that is not built yet stops with exit code 2 and the message
`not built yet (Built in Step N)`.

Exit codes: `0` success, `1` the run failed (for example the database cannot be reached), `2` a configuration
problem, a bad flag, or a stage that is not built yet.

## Database

The schema lives in `../supabase/migrations/` (Step 2 owns 0001 to 0004; A.13.3 lists the rest):

| File | Contents |
|---|---|
| `0001_core.sql` | Tables, triggers, the AI cache and batch reservations |
| `0002_views.sql` | Read models for the app and reports, `db_size_mb()` |
| `0003_rls.sql` | Row Level Security, column grants, storage buckets |
| `0004_seed.sql` | Settings, the six wave-1 segments, source health rows |
| `0005_sheet_views.sql` | `v_sheet_leads` for the sheet sync (engine only) |
| `0006_cost_views.sql` | `v_spend_today`, `v_quota_today`, `v_quota_month` (engine only) |
| `0007_learning.sql` | `v_lead_funnel`, `weight_versions`, `reports` |
| `0008_llm.sql` | AI router storage; already created by 0001, kept for numbering |
| `0009_sheet_targets.sql` | Separate snapshot keys for the staging sheet (`staging_master`, `staging_caller`) and the Step 13 settings |

Apply pending migrations with either tool; both record history in `supabase_migrations.schema_migrations`:

```bash
uv run nlead db migrate --env dev --dry-run    # list what would be applied
uv run nlead db migrate --env dev
npx supabase@3.1.0 migration list --remote="$DATABASE_URL"   # the Supabase CLI sees the same history
npx supabase@3.1.0 db push --remote="$DATABASE_URL"          # the CLI equivalent of nlead db migrate
```

How the data is protected (Step 2.8):
- The engine connects as the database owner through the pooler and bypasses RLS. App users connect as the
  `authenticated` role and every table has RLS; anonymous visitors get nothing.
- Money (`leads.deal_value_inr`) is never granted to app users. Admins read it through `v_leads_admin`; the
  engine reads `v_pipeline` and `v_sheet_leads`.
- Every view runs with the caller's rights (`security_invoker = true`) except `v_leads_admin`.
- Database triggers write the `lead_created`, `stage_change`, `grade_change` and `message_edited` activities.
  Code never inserts those four; it labels its writes with `db.tx(source="sheet", context={"sheet": "master"})`.
- Objects added after 0003 are private until their migration grants them (2.8.4).

Rules: never edit a migration that has been applied; add the next number. Push to dev first, run the tests,
then prod (Step 21).

## Sheet sync and schedules

- **Which sheets:** prod writes `SHEET_MASTER_ID` (founder, with money) and `SHEET_CALLER_ID` (associate, never
  any money). Dev writes both views into `SHEET_STAGING_ID`, the caller tabs ending in ` (caller)`. Staging keeps
  its own snapshots, so a staging run can never disturb the live sheets even on the shared database.
- **Ownership:** every spreadsheet belongs to a person and is shared with the service account as Editor. The
  service account cannot own files (Google gives it no Drive storage), so it cannot create a sheet itself.
  `nlead sheet check` shows whether each sheet is reachable and set up.
- **Safety:** push builds every request first and writes each view in one atomic batch; the snapshot and the
  `sheet_state` marker are saved only after a full write. Pull skips a sheet whose last push did not finish, and
  compares each sheet with its own snapshot (D-045). A live sheet the engine has never written is refused until
  it is adopted with `nlead sheet pull --seed-snapshots` (Step 20.6). Kill switch: `settings.sheet_sync_enabled`.
- **Schedules:** `.github/workflows/` runs night (02:00 IST), morning (06:00), sheet sync (every 2 hours, 09:00
  to 21:00), weekly (Monday 07:00), monthly (the 1st, 22:30) and backup (Sunday 23:00). Scheduled runs stay off
  until the repository variable `SCHEDULES_ENABLED` is `true` (go-live, Step 21); manual runs always work.
  Secrets and variables are set at repository level; each workflow passes `SHEET_MASTER_ID` and
  `SHEET_CALLER_ID` to prod runs only and `SHEET_STAGING_ID` to dev runs only (dev refuses live ids).
  A failed scheduled run opens or updates one GitHub issue per workflow.

## Tests

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest                  # everything, including database and RLS tests
uv run pytest -m "not live"    # what CI runs: no real APIs, no dev database
```

Database tests never touch Supabase. The suite starts a throwaway Postgres in a temp folder on a free
localhost port (initdb and pg_ctl from the installed binaries), applies `tests/sql/auth_stub.sql` (the parts of
Supabase the schema needs, including its default grants) and every migration through the same code as
`nlead db migrate`, and deletes it afterwards. Running Postgres services are never started or touched.

| Variable | Effect |
|---|---|
| `NLEAD_PG_BIN` | Folder with `initdb` and `pg_ctl` (default: the newest installed version) |
| `NLEAD_TEST_DATABASE_URL` | Use this server instead (CI's service container); a fresh database is created and dropped |
| `DATABASE_URL_DEV`, `RLS_ADMIN_ID`, `RLS_CALLER_ID`, `RLS_VIEWER_ID` | Enable the `live` RLS test against the dev project (2.10) |

What is covered: settings safety rules, logging, database helpers, run bookkeeping, the CLI (every command has
`--help`, flags in both positions, clear failures), migrations (order, idempotency, rollback of a failing file),
schema behaviour (seeds, triggers, constraints, every view), RLS for each role (`supabase/tests/rls_test.sql`
plus finer checks), the shared names against the database's CHECK constraints, segment files and their helpers.

## Project layout

```
engine/
  pyproject.toml, uv.lock, .python-version
  config/          scoring.yaml, exclusions.yaml, prices.yaml and tasks.yaml (Step 4)
  segments/        one YAML file per market
  prompts/         AI prompt files (Step 4)
  evals/           golden-set evaluation (Step 17)
  src/nument_engine/
    cli.py         the nlead command
    settings.py    environment settings and their safety rules
    logging.py     JSON logs with the run id on every line
    db.py          connection pool, transactions, upserts, settings helpers
    models.py      shared names (A.12) and AI output models (A.13.1)
    segments.py    segment models, loader, helpers and database sync
    pipeline/      stages and run bookkeeping (runs.py)
    llm/ sources/ research/ sheet/ learn/ ops/   filled by Steps 4 to 22
  tests/           pytest suite, sql/auth_stub.sql, fixtures/
```

## Rules

- Never commit secrets. Only `.env.example` is tracked; `engine/.env.*` and `web/.env.local` are ignored and
  kept at permission 600.
- Dev never writes to the founder's live sheets; the settings refuse to load if it is configured to.
- Public data only (A.4): no logins, no CAPTCHAs, no LinkedIn or X fetching, honest User-Agent, robots.txt
  respected, phone numbers only where the business published them.
- Logs and error messages never contain connection strings or keys.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Configuration error for APP_ENV=dev` | A required value is missing, or live sheet ids are set in dev | Fix `engine/.env.dev` as the message says |
| `cannot reach the database` | Wrong `DATABASE_URL`, or the Supabase project is paused | Use the session pooler string (port 5432); resume the project in the dashboard |
| `prepared statement ... does not exist` | The transaction pooler (port 6543) | Use port 5432 |
| `not built yet (Built in Step N)` | That stage is still a stub | Expected until Step N lands |
| Tests skip with "No Postgres binaries found" | No local PostgreSQL | `brew install postgresql@17`, or set `NLEAD_PG_BIN` / `NLEAD_TEST_DATABASE_URL` |
| `uv sync` picks another Python | System Python is newer | `.python-version` pins 3.12; run `uv python install 3.12` |
