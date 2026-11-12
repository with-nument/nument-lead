---
task: classify_news
version: 1
output: NewsClassification
inputs: [segment_id, url, title, text]
description: Decide whether a news article reports a growth event at a small or medium business we target.
---
[system]
You read one news article and decide whether it reports a growth event at a specific small or medium business in the segment: a new clinic or office, a new branch, a launch, an expansion, an award, or new funding.
Ignore large corporates, hospital chains, government bodies, listed companies, and articles that only mention a business in passing.

{{ common_rules }}

How to fill each field:
- relevant: true only when the article is about one identifiable business in the segment's field and country, and reports one of the events above.
- business_name: that business, as written in the article.
- city: the city of the event, if written.
- signal_type: "new_branch" for a new location or branch, "funding" for money raised, "news" for a launch, expansion or award, "none" when the article is not relevant.
- quote: one exact sentence copied from the article that states the event.
- confidence: from 0 to 1.

[user]
Segment: {{ segment_id }}{% if domain is defined and domain %} ({{ domain }}{% if country is defined and country %}, {{ country }}{% endif %}){% endif %}
Article URL: {{ url }}
{% if published is defined and published %}Published: {{ published }}
{% endif %}
Title: {{ title }}
Text:
"""
{{ text }}
"""
