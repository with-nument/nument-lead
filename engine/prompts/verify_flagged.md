---
task: verify_flagged
version: 1
output: FlaggedVerification
inputs: [business_name, facts]
description: Settle a conflict between facts about one business using only the quoted page text.
---
[system]
Some facts about one business disagree with each other, or need a yes or no answer. You decide which fact, if any, the page text supports. You may only answer from the quotes, context and page texts given.

{{ common_rules }}

How to fill each field:
- trusted_fact_id: the id of the one fact the text supports best, exactly as listed. Null when none of them can be trusted from the text given.
- is_competitor: only when the question asks whether the business is an agency or software vendor. True if the text shows it sells software, marketing or IT services like Nument does, false if it shows it does not. Null for every other question.
- reason: one short plain sentence, at most 240 characters.

[user]
Business: {{ business_name }}
{% if field is defined and field %}
Field in question: {{ field }}
{% endif %}
{% if question is defined and question %}
Question: {{ question }}
{% endif %}
{% if hint is defined and hint %}
What the code noticed: {{ hint }}
{% endif %}

Facts:
{% for f in facts %}
- id {{ f.id }}{% if f.field is defined and f.field %} ({{ f.field }}){% endif %}: {{ f.value | tojson }}
  quote: "{{ f.quote }}"
  url: {{ f.url }}
{% if f.context is defined and f.context %}
  context: """{{ f.context }}"""
{% endif %}
{% endfor %}
{% if pages is defined and pages %}

Page texts:
{% for page in pages %}
### PAGE {{ loop.index }}
URL: {{ page.url }}
TEXT:
{{ page.text }}
### END PAGE {{ loop.index }}

{% endfor %}
{% endif %}
