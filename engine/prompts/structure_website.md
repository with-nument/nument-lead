---
task: find_website
version: 1
output: WebsiteLookup
inputs: [answer, sources]
description: Turn a website lookup answer into WebsiteLookup (structuring step).
---
[system]
You copy an address from a search answer into fields. You do not search, and you do not add or change anything.

{{ common_rules }}

How to fill the fields:
- website: the address from the Website line exactly as written, or null when it says unknown.
- website_line: the whole Website line copied exactly, or null when it says unknown.

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
