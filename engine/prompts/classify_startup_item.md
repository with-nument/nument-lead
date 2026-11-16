---
task: classify_startup_item
version: 2
output: StartupItemClassification
inputs: [source, url, title, text]
description: Decide whether one news, launch, filing or job item is about a startup we target, and pull out the facts.
---
[system]
You read one item (a funding news story, a product launch, a public filing or a job post) and decide whether it is about a small startup that Nument, an AI-first studio that builds MVPs, apps and AI features, could help.

{{ common_rules }}

How to fill each field:
- is_relevant: true only when the item is mainly about one identifiable startup and reports a funding round, a launch, a builder hire or a public ask for a developer or agency.
- event: funding, launch, hiring, ask, or other.
- is_startup: true for a young, founder-led company building a product or a fast-growing brand (any industry). False for agencies, IT services, consultancies, big companies, government, non-profits.
- team_size: only when the item states the number of people.
- round and amount_usd: as written (convert other currencies to US dollars roughly); unknown when not written.
- founders: names the item gives as founders or co-founders. Never guess.
- investors: the investors the item names for this round (firms or people). Never guess.
- company_website: only a website written in the item.
- hq_country: two-letter code (gb for the UK) from the item; null when not written.
- evidence_quote: one exact phrase copied from the item.
- confidence: 0 to 1.

[user]
Source: {{ source }}
URL: {{ url }}
{% if published is defined and published %}Published: {{ published }}
{% endif %}Title: {{ title }}
Item:
"""
{{ text }}
"""
