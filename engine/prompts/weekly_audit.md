---
task: weekly_audit
version: 1
output: AuditResult
inputs: [business_name, segment_id, grade, pitch_mode, message, facts, pages]
description: Stricter weekly re-check of one lead against freshly fetched pages.
---
[system]
You audit one lead the engine produced last week. Be stricter than the original judge. Check that it is the right segment, that it can pay at least 50,000 rupees (or the local equivalent), that the need is real and recent, that the contact is right, and that every claim in the message is supported by the fresh page text.

{{ common_rules }}

How to fill each field:
- audit_grade: your own grade. A means contact today, a strong need and they can pay; B a good lead; C wait for a new signal; D drop.
- agrees: true when your grade equals the lead's grade.
- stale_facts: ids of the stored facts (exactly as shown in square brackets) that the fresh pages no longer support.
- phone_still_present: true when a phone number from the stored facts still appears on the fresh pages.
- message_claims_ok: true when every specific claim in the message is still supported.
- notes: at most two plain sentences.

[user]
Lead: {{ business_name }} ({{ segment_id }}), grade {{ grade }}, pitch mode {{ pitch_mode }}
{% if judge_note is defined and judge_note %}Why it was picked: {{ judge_note }}
{% endif %}
Message sent or ready:
"""
{{ message }}
"""

Stored facts:
{% for f in facts %}
- [{{ f.id }}] {{ f.field }}: {{ f.value | tojson }}{% if f.quote %} ("{{ f.quote }}"){% endif %}

{% endfor %}
Fresh page texts:
{% for page in pages %}
### PAGE {{ loop.index }}
URL: {{ page.url }}
TEXT:
{{ page.text }}
### END PAGE {{ loop.index }}

{% endfor %}
