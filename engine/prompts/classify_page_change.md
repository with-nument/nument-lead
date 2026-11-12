---
task: classify_page_change
version: 1
output: PageChangeClassification
inputs: [business_name, url, old_text, new_text]
description: Say what changed between two versions of a business's careers or locations page.
---
[system]
You compare the old and the new text of one business's careers or locations page and say what changed.

{{ common_rules }}

How to fill each field:
- change_type: "new_job" when a new job opening appears, "new_branch" when a new location or branch appears, "removed" when only openings or locations were removed, "cosmetic" for wording, dates or layout only, "other" for anything else.
- roles: the titles of the new job openings, as written in the new text. Empty when there are none.
- quote: one exact sentence or line copied from the NEW text that shows the change. Null for "removed" or "cosmetic".
- signal_type: "hiring_frontdesk" for a new receptionist, front desk, telecaller, patient coordinator, admissions counsellor, customer support or sales role; "hiring_builder" for a new developer, automation, AI or tech role; "new_branch" for a new location; "none" otherwise.

[user]
Business: {{ business_name }}
Page: {{ url }}
Old text{% if old_date is defined and old_date %} (fetched {{ old_date }}){% endif %}:
"""
{{ old_text }}
"""
New text{% if new_date is defined and new_date %} (fetched {{ new_date }}){% endif %}:
"""
{{ new_text }}
"""
