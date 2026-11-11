# Prompts

One Markdown file per AI task (`classify_signal.md`, `extract_facts.md`, `judge_lead.md`, `write_message.md`,
...), each with front matter (`task`, `version`, `output`), a system part and a Jinja2 user template. The output
model named in the front matter is defined in `src/nument_engine/models.py` (A.13.1).

The files are written in Step 4 from Appendix A of `IMPLEMENTATION_PLAN.md`. Every prompt must work the same on
Gemini and OpenAI, because every task can fall back to Gemini.
