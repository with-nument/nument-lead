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

Input names follow Appendix A of the plan. Required inputs must be passed; the optional ones are used when
present. Lists of facts and signals are dicts with the keys shown.

| File | Task | Output | Required inputs | Optional inputs |
|---|---|---|---|---|
| `classify_signal.md` | `classify_signal` | `SignalClassification` | segment_id, domain, country, source, url, text | title, employer, address, posted_date |
| `classify_news.md` | `classify_news` | `NewsClassification` | segment_id, url, title, text | domain, country, published |
| `classify_page_change.md` | `classify_page_change` | `PageChangeClassification` | business_name, url, old_text, new_text | old_date, new_date |
| `extract_facts.md` | `extract_facts` | `FactsExtraction` | segment_id, business_name, website, pages `[{url, text}]` | country, context, structured_data, tech_flags |
| `verify_flagged.md` | `verify_flagged` | `FlaggedVerification` | business_name, facts `[{id, value, quote, url}]` | field, question, hint, facts[].field, facts[].context, pages `[{url, text}]` |
| `judge_lead.md` | `judge_lead` | `LeadJudgement` | segment_id, pitch_mode, total, fit, can_pay, intent, reach, grade, facts `[{id, field, value}]`, signals `[{id, type}]`, allowed_angles | country, city, business_name, packaged_outcome_name, reasons (dict or list), rule_note, contacts_summary, angles `[{key, idea}]`, facts[].quote, signals[].category, age_days, quote, details |
| `write_message.md` | `write_message` | `MessageDraft` | segment_id, pitch_mode, angle, business_name, seen_where, facts `[{id, field, value}]`, signals `[{id, type}]`, associate_name | greeting, person_name, person_role, country, country_name, city, angle_label, angle_idea, need, what_we_saw, packaged_outcome_name, packaged_outcome, country_notes, needs_email, feedback, avoid_openers, avoid_questions, signals[].summary |
| `check_message.md` | `check_message` | `MessageCheck` | message, facts | signals, greeting, pitch_mode, angle |
| `grounded_public_asks.md` | `grounded_search` (search call) | free text with citations | domain, country, days, queries | cities |
| `structure_public_asks.md` | `grounded_search` (structuring call) | `PublicAskResults` | answer, sources (filled by the router) | queries |
| `weekly_audit.md` | `weekly_audit` | `AuditResult` | business_name, segment_id, grade, pitch_mode, message, facts, pages | judge_note |

`nument_engine.llm.health.SMOKE_INPUTS` has one complete, working example of the inputs for every task.
