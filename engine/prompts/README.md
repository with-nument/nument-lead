# Prompts

One file per AI task, rendered by `nument_engine.llm.prompts` and sent through the router
(`nument_engine.llm.router`). Each file has front matter, a `[system]` part and a `[user]` part, both Jinja2:

```
---
task: judge_lead
version: 1
output: LeadJudgement            # model in nument_engine.models (A.13.1), or null for free text
inputs: [segment_id, facts]      # required inputs; any other variable must use `| default(...)`
description: one line
---
[system]
...
[user]
...
```

Rules:

- Every template can use `{{ common_rules }}` (the shared rules in `_common_rules.md`) and `{{ today }}`.
- Output format comes from the schema, not from prose: never paste a JSON example into a prompt.
- Prompts must work the same on Gemini and OpenAI, because every task can fall back to Gemini.
- Any wording change bumps `version`. Stored outputs carry `provider:model#task.vN`, so the weekly report
  can compare versions. A prompt change must pass `nlead eval` on its primary and first Gemini fallback.
- No en or em dashes anywhere (the founder's rule; a test checks it).

| File | Task | Output | Required inputs |
|---|---|---|---|
| `classify_signal.md` | `classify_signal` | `SignalClassification` | segment_id, domain, country, source, url, text (optional: title, employer, address, posted_date) |
| `classify_news.md` | `classify_news` | `NewsClassification` | segment_id, domain, country, url, title, text (optional: published) |
| `classify_page_change.md` | `classify_page_change` | `PageChangeClassification` | business_name, url, old_text, new_text (optional: old_date, new_date) |
| `extract_facts.md` | `extract_facts` | `FactsExtraction` | business_name, segment_id, country, website, pages `[{url, text}]` (optional: context) |
| `verify_flagged.md` | `verify_flagged` | `FlaggedVerification` | business_name, field, facts `[{id, value, quote, url, context?}]` (optional: question) |
| `judge_lead.md` | `judge_lead` | `LeadJudgement` | segment_id, country, pitch_mode, rule_grade, score `{total, fit, can_pay, intent, reach}`, reasons, facts `[{id, field, value, quote}]`, signals `[{id, type, category, quote, details, age_days?}]`, allowed_angles, packaged_outcome (optional: city, contacts) |
| `write_message.md` | `write_message` | `MessageDraft` | segment_id, country, pitch_mode, angle, business_name, greeting, seen_where, what_we_saw, idea, facts `[{id, field, value}]`, signals `[{id, type, summary}]`, associate_name, need_email (optional: feedback, avoid) |
| `check_message.md` | `check_message` | `MessageCheck` | message, facts, signals (optional: pitch_mode) |
| `grounded_public_asks.md` | `grounded_search` (search call) | free text with citations | domain, country, days, queries (optional: cities) |
| `structure_public_asks.md` | `grounded_search` (structuring call) | `PublicAskResults` | answer, sources (filled by the router) |
| `weekly_audit.md` | `weekly_audit` | `AuditResult` | business_name, segment_id, grade, pitch_mode, message, facts, pages (optional: judge_note) |
