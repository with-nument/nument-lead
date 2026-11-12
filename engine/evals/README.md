# Evals

The golden-set evaluation (Step 17.3 and 17.4 of `IMPLEMENTATION_PLAN.md`). It measures lead quality before
any prompt, model, weight, segment or rule change goes live, and it is the CI eval gate.

| File | What it is |
|---|---|
| `run_eval.py` | `nlead eval`: chooses businesses, runs the pipeline, scores, stores a `reports` row |
| `golden.py` | The golden files: loading, validation, the fixed CI subset, export from the database |
| `measures.py` | The metrics and thresholds |
| `pipeline.py` | How one business is evaluated: production stages on frozen pages, or a saved replay |
| `golden/` | The golden set, exported from the app's labels and committed |

## Commands

Run from `engine/`:

```bash
uv run nlead eval --export-golden --env dev   # labels, frozen pages and the subset, from the database
uv run nlead eval --dry-run                    # validate the files and show the selection; no AI calls
uv run nlead eval --subset 20 --env dev        # the fixed CI subset, about ₹60
uv run nlead eval --env dev                    # all labelled businesses, about ₹300
uv run nlead eval --segment clinics-ae         # one segment (repeatable)
uv run nlead eval --save-outcomes out.jsonl    # keep each business's outcome...
uv run nlead eval --replay out.jsonl           # ...and re-check the metrics later for free
```

Exit codes: `0` every threshold passed, `1` a threshold failed, `2` cannot run yet (no golden set, or a
pipeline stage not built), `3` skipped because today's spend plus the eval would pass the daily cap.

## Golden files

### `golden/labels.jsonl`
One business per line, written by `--export-golden` from `golden_labels`:

```json
{"business_id": "6f1c0e2a-...", "segment": "clinics-in", "label": "good", "reasons": ["great_lead"], "labeled_at": "2026-12-01", "name": "Example Fertility Centre"}
```

`label` is `good` or `bad`. `reasons` use the fixed list of Step 16.5: `wrong_segment`, `too_small`,
`too_big_or_corporate`, `agency_or_vendor`, `no_real_need`, `cannot_reach`, `already_has_solution`,
`bad_message`, `great_lead`, `other`. Aim for 100 labels, about half good and half bad, spread as 25
`clinics-in` and 15 for each other wave-1 segment.

### `golden/facts_truth.yaml`
Facts checked by hand against the business's own pages, for 30 businesses (5 per segment). A missing value
means "not checked", never "false". Only fields the extraction produces are checked.

```yaml
- business_id: "6f1c0e2a-..."
  segment: clinics-in
  checked_by: builder
  checked_at: 2026-12-01
  facts:
    decision_maker: {name: "Dr. Example Name", role: "Founder"}
    phones:
      - {e164: "+919800000000", type: mobile}
    branches_count: 12
    staff_count_min: 30
    booking_method: "phone and WhatsApp"   # words from: online_widget, phone, whatsapp, form, none
    whatsapp_present: true
    chat_widget: false
    has_in_house_tech: "no"                # yes, no or unknown
    is_agency_or_vendor: false
    services_include: ["ultrasound", "radiology"]
```

### `golden/subset20.txt`
The fixed CI subset, one business id per line, chosen with seed 42: 4 from `clinics-in` and 3 from each
other wave-1 segment (plus one more to make 20), half good and half bad, with at least 6 hand-checked
businesses. `--export-golden` rewrites it.

### `golden/pages/<business_id>.json`
The business's pages frozen at export time, so evals never re-crawl and stay repeatable:
`{"business_id", "segment", "name", "exported_at", "pages": [{"url", "title", "fetched_at", "text_hash", "text"}]}`.
Golden businesses are excluded from page pruning, so their text is still there when you export.

## Metrics and thresholds

| Metric | Definition | Full set | Subset of 20 |
|---|---|---|---|
| Fact precision | Verified facts that match `facts_truth.yaml` / verified facts checked | 95% | 95% |
| Field recall | Truth fields the extraction found and verified / truth fields that can be quoted | 80% | 75% |
| Phone accuracy | Top contact phone equals a truth phone / businesses with a truth phone | 95% | 90% |
| Grade precision | Share labelled good among the highest totals (50 for the full set, 10 for the subset) | 80% | 70% |
| Bad rejection | Businesses labelled bad that were graded C or D | 70% | 60% |
| Message lint pass | Messages that pass lint on the first attempt | 98% | 95% |
| Critic score | Mean `check_message` score, 0 to 10 | 8.5 | 8.0 |
| Unverified claims | Message claims not linked to a verified fact or signal | 0 | 0 |
| Businesses that errored | A run where many businesses fail cannot pass | at most 10% | at most 10% |

A metric with nothing to measure in a run (for example no hand-checked business) is shown as "not measured"
and does not fail the run on its own. Every run is stored as a `reports` row of kind `eval`; the weekly
report shows the latest one.

## In CI

The `eval-gate` job runs `nlead eval --subset 20 --env dev` on pull requests that change prompts,
`tasks.yaml`, prices, exclusions, scoring, segments, this folder, or the extract, verify, score, judge and
message stages. Until `golden/labels.jsonl` is committed, the job posts a notice and passes.

## Keeping the set useful

- Add 10 labels a month from thumbed leads (the app promotes a thumbed lead with one click).
- Re-check the hand-checked facts of 5 businesses a quarter.
- Label 20 businesses for a new segment before it gets a real quota (Step 23).
