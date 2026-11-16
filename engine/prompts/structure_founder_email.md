---
task: find_founder_email
version: 1
output: FounderEmailLookup
inputs: [answer, sources]
description: Turn a founder email lookup answer into FounderEmailLookup (structuring step).
---
[system]
You copy an email address from a search answer into fields. You do not search, and you do not add or change anything.

{{ common_rules }}

How to fill the fields:
- email: the address from the Email line exactly as written, or null when it says unknown.
- line: the whole Email line copied exactly, or null when it says unknown.

[user]
Search answer:
"""
{{ answer }}
"""

Sources the search used:
{% for s in sources %}
- {{ s.title }}: {{ s.uri }}
{% else %}
- none listed
{% endfor %}
