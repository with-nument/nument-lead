# Segments guide

A segment is one market: a domain in a country, for example `clinics-in`. Each segment is one YAML file in
`engine/segments/`, validated by `engine/src/nument_engine/segments.py`. Adding a market means adding a file,
not changing code. Every key is explained in Step 3.3 of `IMPLEMENTATION_PLAN.md`; `clinics-in.yaml` is the
fully commented reference.

Check a change with:

```bash
cd engine
uv run pytest tests/test_segments.py -q
uv run nlead db sync-segments --dry-run --env dev   # validate only
uv run nlead db sync-segments --env dev             # copy the files into the segments table
```

The sync writes `config`, `config_version` and `enabled` on every run. `daily_quota` comes from the file only
when a segment is first inserted; after that the founder changes it in the app.

## How to add a new segment

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

## Places daily caps

The `places` caps above keep the totals inside the free allowances (A.10.2). Step 5 enforces the same totals at run time with the settings `places_details_cap_in` (230) and `places_details_cap_global` (30).

| Region | Details per day | Reviews per day | Free cap per day, per SKU |
|---|---|---|---|
| India | clinics 90 + real estate 60 + education 50 = 200 | 90 + 60 + 40 = 190 | 230 |
| UAE (abroad) | 14 + 9 + 7 = 30 | 10 + 7 + 5 = 22 | 30 |

Verify at build which pricing applies to the founder's billing account, and set the same caps as quotas in the Google Cloud console as a second safety net.

## Verify at build (wave 1)

1. Download Overture `taxonomy.csv` for the current release. Confirm every code in `overture.categories` and `fit.categories`, remove codes that do not exist, and delete the `# verify at build` comment from confirmed ones. Real estate and education have **no confirmed codes yet**.
2. Confirm the Places primary types used in `fit.categories` and `ticket_class` (`dentist`, `doctor`, `skin_care_clinic`, `physiotherapist`, `real_estate_agency`).
3. Draw every `bbox` on a map. It must cover the built-up area and not waste queries on sea or desert.
4. Open each `verify_at_build` registry. Check robots.txt, login and CAPTCHA. Set `status: ready` only if it is public and allowed (and add its key to `source_records_source_known`, 2.6.1); otherwise delete the entry.
5. Check that chain domains in `exclusions.yaml` are still the companies' real domains.
6. Run each `news_queries` entry once in the GDELT DOC API and each `public_ask_queries` entry once in grounded search; drop queries that return nothing useful.
7. Run `subcategory_for()` on 50 real business names per segment and fix `match` lists that pick the wrong class.

## Pitfalls

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
