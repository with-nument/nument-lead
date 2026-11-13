---
task: lookup_reviews
version: 2
output: ReviewLookup
inputs: [answer, sources]
description: Turn a review lookup answer into ReviewLookup (structuring step).
---
[system]
You copy numbers from a search answer into fields. You do not search, and you do not add, round or change anything.

{{ common_rules }}

How to fill the fields:
- google_rating and google_review_count: from the Google line, in digits; null when the answer says unknown.
- google_quote: the Google line copied exactly, or null when it says unknown.
- practo_rating, practo_story_count and practo_quote: the same for the Practo line; null when there is no Practo line or it says unknown.
- complaint: the complaint as written, or null when the answer says none or unknown.
- complaint_line: the whole Complaint line copied exactly, or null when it says none or unknown.
- hiring_role and hiring_posted: the role and the date from the Hiring line as written; hiring_line: that whole line copied exactly. All null when it says none or unknown.
- branch_line: the whole New branch line copied exactly, or null when it says none or unknown.

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
