# Decisions

Changes to the plan made while building and running the system, newest first. Each entry says what changed,
why, and how to undo it. The plan itself is [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).

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
