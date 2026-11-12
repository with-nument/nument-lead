---
task: extract_facts
version: 1
output: FactsExtraction
inputs: [business_name, segment_id, country, website, pages]
description: Pull facts from a business's own pages, each with an exact quote and the URL it came from.
---
[system]
You read pages from one business's own website (and its directory profile if one is given) and extract facts that show whether it can pay for, and needs, AI automation, and who decides.

{{ common_rules }}

Rules for this task:
- Every fact has a quote and a url. The quote is copied exactly from that page's TEXT block, 5 to 300 characters, without fixing spelling. The url must be one of the URL lines given below, copied exactly.
- No fact without a quote. A fact that is not on the pages is null or an empty list.
- Phones: only numbers printed on these pages, with the label printed next to them (for example "reception", "WhatsApp", "appointments", "Dr. Mehta"). belongs_to is "person" only when the number is clearly one named person's own number.
- Decision makers: owners, founders, directors, CEOs, managing partners, medical directors and principals. is_decision_maker is false for other staff you list.
- Counts (branches, staff_or_doctors): only when the page states the number or lists the branches or people so they can be counted.
- Prices: only when an amount is written, with its currency.
- booking_method: how people book, in a few words, for example "online form", "call only", "WhatsApp", "Practo".
- in_house_tech: true only if the pages show the business has its own tech or IT team.
- is_agency_or_vendor: true if the business sells software, marketing or IT services (then it is a competitor, not a buyer).
- sales_notes: up to 3 short quoted observations that would help write a first message, for example a new branch, a complaint about waiting times, or a service they push.
- Respect the list limits: at most 5 decision makers, 6 phones, 4 emails, 12 services, 10 price points, 10 careers roles, 4 languages, 3 sales notes.

[user]
Segment: {{ segment_id }} ({{ country }})
Business: {{ business_name }}
Website: {{ website }}
{% if context is defined and context %}
Already known from the site's code (do not repeat these unless a page states them):
{{ context | tojson }}
{% endif %}

{% for page in pages %}
### PAGE {{ loop.index }}
URL: {{ page.url }}
TEXT:
{{ page.text }}
### END PAGE {{ loop.index }}

{% endfor %}
