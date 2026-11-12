# Runbook

How to keep Nument Leads healthy: a short routine, the commands behind it, and what to do when something
looks wrong. The build manual is `IMPLEMENTATION_PLAN.md` (Step 22 is the source of this page); the rules
for data and outreach are in [data-policy.md](data-policy.md); incidents go in [incidents.md](incidents.md).

Commands below run from `engine/` with `uv run`, for example `uv run nlead health --env prod`. Every
command accepts `--env dev|prod`, `--segment ID`, `--limit N` and `--dry-run`.

- [Routine](#routine)
- [Reading `nlead health`](#reading-nlead-health)
- [The weekly learning loop](#the-weekly-learning-loop)
- [The golden set and the eval gate](#the-golden-set-and-the-eval-gate)
- [Retention and database size](#retention-and-database-size)
- [Troubleshooting](#troubleshooting)

## Routine

### Daily (5 minutes)

1. Open the app's **Engine** page:
   - Did last night's run (02:00 IST) and this morning's run (06:00 IST) finish `ok`?
   - How many leads were added today, and how many are A and B?
   - What is today's spend against the ₹750 cap?
   - Is any source blocked or switched off?
2. Open **Today** and send the messages.
3. If anything is red, check [Troubleshooting](#troubleshooting). `nlead health` gives the same picture in a
   terminal, and every scheduled run appends it to its GitHub job summary.

### Weekly (Monday, 30 minutes)

The weekly workflow runs at 07:00 IST: re-weighting, then the audit, then the report.

1. Read the weekly report (app: **Insights**, tab **Weekly report**; also in the workflow's job summary).
2. Act on the **scale** and **cut** suggestions by changing segment switches or daily quotas on the Engine
   page. The engine only recommends; it never switches anything off by itself.
3. Mark the five audit leads (Leads, filter **Audit this week**) as correct or wrong, with a reason.
4. Promote 5 to 10 thumbed leads into the golden set.
5. Check GitHub Actions minutes for the month (Settings, Billing and plans) and the database size
   (`nlead health`, or the Supabase dashboard, Reports).

### Monthly (first Monday, 1 hour)

1. Confirm the monthly universe refresh ran and used the new Overture release (Engine page, last monthly run).
2. Compare `engine/config/prices.yaml` with the official Gemini, OpenAI and Google Maps pricing pages; update
   `verified_on` and commit if anything changed.
3. Merge green Dependabot pull requests (the eval gate must be green when it ran).
4. Review the suppression list and any deletion requests ([data-policy.md](data-policy.md#deletion-requests)).
5. Review app users and roles; remove anyone who left.
6. Cost review: month spend against the budget, cost per good lead and per meeting (weekly reports).
7. Check Places API usage against the free caps (Google Cloud console, APIs and services, Metrics).

The monthly workflow also applies the retention rules (`nlead health --prune`).

### Quarterly (half a day)

1. Rotate the Gemini, OpenAI and Maps keys and the Google service-account key; renew `GH_DISPATCH_TOKEN`
   (90-day token). Update GitHub and Render secrets the same day.
2. Restore test: restore the latest encrypted backup into a scratch Supabase project or a local Postgres,
   run the migrations first, check row counts, then delete the scratch database.
3. Model review: run the full golden eval (`nlead eval --env dev`) with any newer or cheaper model in
   `engine/config/tasks.yaml`; switch only if every threshold still passes.
4. Re-check the hand-checked facts of 5 golden businesses (websites change).
5. Re-read the country rules for every enabled country ([data-policy.md](data-policy.md#country-rules)).

## Reading `nlead health`

```
uv run nlead health --env prod            # table; exit code 1 if any check fails
uv run nlead health --env prod --summary  # markdown for a job summary
uv run nlead health --env prod --notify   # also email new alerts (once a day per alert)
```

| Status | Meaning | The night and morning runs |
|---|---|---|
| `ok` | Fine | Continue |
| `info` | Worth knowing (a source switched off, OpenAI off, dev without a staging sheet) | Continue |
| `WARN` | Look today (a blocked source, spend past 80% of the cap, a stuck batch, database over 350 MB) | Continue |
| `ALERT` | Act now (last run failed, spend at the cap, Gemini breaker open, database over 400 MB) | Continue, and email the founder |
| `FAIL` | Running now is unsafe or pointless (pending migrations, Gemini off or without a key) | Stop |

| Check | What it looks at |
|---|---|
| `database` | Reachable, and its size against the 500 MB free tier |
| `migrations` | Every file in `supabase/migrations` is applied |
| `ai.gemini`, `ai.openai` | Provider switches (`settings.providers_enabled`) and keys. Gemini must run every task |
| `ai.<provider>.breaker` | An open circuit breaker and its cool-off end (Step 4.5) |
| `google.maps_key`, `sheets` | Places and PageSpeed key; service account and sheet ids for this environment |
| `spend` | Today's AI and API spend against `daily_cap_inr` and `alert_pct` |
| `quota.*` | Grounded searches and Places details today and this month against the free amounts |
| `source.*` | Every source: blocked, error, switched off, or no success in 3 days |
| `run.*` | The last night, morning, sheet, weekly and monthly runs: failed, partial, stuck or too old |
| `ai.batches` | AI batches waiting more than 24 hours |

## The weekly learning loop

Every Monday `nlead learn` proposes new scoring weights from outcomes (Step 16.4):

- Success is a meeting inside 45 days of first contact (a reply inside 21 days until the segment has 15
  meetings). Only signal types and can-pay proxies seen on 30 or more mature leads change.
- A number moves at most 20% a week and never outside half to double its default.
- Segments with 200 or more mature outcomes try a logistic model first; it is used only when it clearly
  beats the current score on held-out data.
- Nothing is applied unless the golden set, re-scored with the proposal, still passes the grade thresholds.
  The weekly report says what changed, and why a proposal was rejected.

| Task | How |
|---|---|
| See what would change | `uv run nlead learn --dry-run --env prod` |
| Freeze the weights | Engine page, or set `settings.score_weights_frozen` to `true` |
| Restore an older version | Engine page, or `uv run nlead learn --rollback VERSION --env prod` (recorded as a new version) |
| History | `weight_versions` table: every version with its method, reason and diff |

## The golden set and the eval gate

The golden set is 100 businesses the founder labelled good or bad (Step 17.3), stored in `golden_labels` and
exported to `engine/evals/golden/` for CI. Its formats are in [engine/evals/README.md](../engine/evals/README.md).

| Task | Command |
|---|---|
| Export labels, frozen pages and the CI subset | `uv run nlead eval --export-golden --env dev`, then commit `engine/evals/golden/` |
| Run the CI subset (20, about ₹60) | `uv run nlead eval --subset 20 --env dev` |
| Run the full set (about ₹300) | `uv run nlead eval --env dev` |
| Re-check saved outcomes, free | `uv run nlead eval --save-outcomes out.jsonl`, later `--replay out.jsonl` |

Exit codes: `0` passed, `1` a threshold failed, `2` cannot run yet (no golden set, or a stage not built),
`3` skipped because today's budget cannot cover it.

**CI eval gate.** Pull requests that change prompts, `tasks.yaml`, prices, exclusions, scoring, segments,
the eval, or the extract, verify, score, judge and message stages run the 20-business subset on dev. A
failed threshold or a budget skip blocks the merge. Until the golden set is committed, the job posts a
notice and passes. It needs the repository secrets `DEV_DATABASE_URL` and `GEMINI_API_KEY`
(`GEMINI_API_KEY_BACKUP` and `OPENAI_API_KEY` are optional).

**Branch protection.** On GitHub (Settings, Branches, rule for `main`): require the `engine`, `secrets` and
`eval-gate` checks and one approval. Turn it on once the go-live cutover is done.

**Keeping it fresh.** Add 10 labels a month from thumbed leads, re-check 5 hand-checked businesses a
quarter, and label 20 businesses before a new segment gets a real quota.

## Retention and database size

`nlead health --prune` (monthly workflow; `--dry-run` counts only) applies the rules in
[data-policy.md](data-policy.md#retention). The free tier holds 500 MB. `nlead health` warns at 350 MB and
alerts at 400 MB. The levers, in order: shorter page text retention for non-leads, then a Supabase upgrade
(a founder decision).

```sql
-- size by table
select relname, pg_size_pretty(pg_total_relation_size(relid)) as size
from pg_catalog.pg_statio_user_tables order by pg_total_relation_size(relid) desc;
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No new leads this morning; no night run on the Engine page | The GitHub schedule did not fire, or the workflow is disabled | Check the Actions tab; re-enable the workflow; run `night.yml` and `morning.yml` by hand |
| Runs fail with "cannot reach the database" | Supabase paused the free project after 7 idle days, or maintenance | Restore the project in the Supabase dashboard; nightly runs keep it active afterwards |
| `nlead health` shows `FAIL migrations` | A migration was added but not applied to this database | `uv run nlead db migrate --env <env>` (dev first, then prod) |
| `FAIL ai.gemini` | Gemini switched off, or `GEMINI_API_KEY` missing | Switch it on in the Engine page; set the secret in GitHub and Render |
| `ALERT ai.gemini.breaker` | Too many Gemini errors, or a quota or billing error | Wait for the cool-off; check the key and billing in Google AI Studio; the backup key is used automatically |
| Places steps log "quota exceeded" | The daily Places cap was reached | Normal at the cap; work continues tomorrow. If it happens early every day, lower the new cities per night |
| Morning run says "batch not ready" | The AI batch is still running | The morning run waits, then leaves the rest for later. Over 24 hours: `nlead extract collect --force-sync` |
| A stage changed in the sheet did not reach the app, or the reverse | Sheet sync skipped, failed, or lost a conflict | Check the last `sheet_sync` run; conflicts are `conflict_overridden` activities; run `nlead sheet sync` |
| The sheet shows an error cell or broken formatting | A push stopped half way, or a formula column was edited | Run `nlead sheet push`; tabs are rebuilt only after a full build |
| A source shows "blocked" | A 403, 429 or challenge page | Do nothing for 7 days; it retries after `blocked_until`. Never work around a block. A grey source blocked twice stays off |
| Spend jumped near the cap early in the day | A task looped, or a price changed | Check `costs` by task for today; the guard already stopped optional work; check `prices.yaml` |
| `eval skipped: budget` in CI | Today's spend plus the eval would pass the cap | Re-run the job after midnight IST, or raise the dev cap for the day |
| The weekly report says "Weights proposal rejected by eval" | The proposal made golden-set grades worse | Nothing to do; the current weights stay. Look at the golden set if it repeats |
| `WARN database` | Over 350 MB | Run `nlead health --prune --dry-run`, then decide on retention or an upgrade |
| Someone cannot log in | Wrong password, removed user, or a stale cookie | The admin resets the password from the app's settings; clear cookies |
| The app takes 30 to 60 seconds to open | The Render free plan was asleep | Expected on the free plan; the Starter plan stays awake |
| The monthly run fails reading Overture | The release path changed | `overture.py` reads the latest release from the catalog; update the catalog URL and re-run `nlead universe --monthly` |
| AI calls fail with "model not found" | A model id was retired | Update `engine/config/tasks.yaml`, run `nlead eval --subset 20`, commit. Fallbacks keep the night running |
| Duplicate leads in the app | Entity resolution missed a match | Merge them in the app and add a test case for `resolve.py` |
| Messages read too alike | Same angle and segment, low variety | Lower the similarity threshold or add angle variety in the segment file |
| Grounded search returns nothing | The 5,000 free monthly queries are used up | Wait for the next month or raise the budget; the engine skips it at the limit |
