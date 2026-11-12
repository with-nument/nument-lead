---
task: verify_flagged
version: 1
output: FlaggedVerification
inputs: [business_name, field, facts]
description: Settle a conflict between facts about one business using only the quoted page text.
---
[system]
Some facts about one business disagree with each other. You decide which one, if any, the page text supports. You may only answer from the quotes and context given.

{{ common_rules }}

How to fill each field:
- trusted_fact_id: the id of the one fact the text supports best. Null when none of them can be trusted from the text given.
- is_competitor: only when the question asks whether the business is an agency or software vendor. True if the text shows it sells software, marketing or IT services like Nument does, false if it shows it does not. Null for every other question.
- reason: one short plain sentence, at most 240 characters.

[user]
Business: {{ business_name }}
Field in conflict: {{ field }}
{% if question is defined and question %}Question: {{ question }}
{% endif %}

Facts:
{% for f in facts %}
- id {{ f.id }}: {{ f.value | tojson }}
  quote: "{{ f.quote }}"
  url: {{ f.url }}
{% if f.context is defined and f.context %}
  context: """{{ f.context }}"""
{% endif %}
{% endfor %}
