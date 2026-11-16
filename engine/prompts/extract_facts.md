---
task: extract_facts
version: 2
output: FactsExtraction
inputs: [segment_id, business_name, website, pages]
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
- in_house_tech: true only if the pages show the business has its own tech or IT team (its own engineers or developers).
- is_agency_or_vendor: true if the business sells building, software, IT, marketing or hiring services to other businesses (then it is a competitor, not a buyer). A company that sells its own product (an app, a SaaS, a marketplace) is not a vendor.
- sales_notes: up to 3 short quoted observations that would help write a first message, for example a new branch, a complaint about waiting times, or a service they push.
{% if domain is defined and domain == "firms" %}

This business is a startup or a young company. Also fill these startup fields, each only when a page states it:
- team_members: the people the pages list as the team (founders and staff; never investors, advisors, mentors or board members). Quote the line that holds the person's name together with their role. is_founder is true for founders and co-founders. is_engineer is true only for people who write code or lead engineering (CTO, engineer, developer, technical co-founder); false for design, product, sales, marketing, operations and research roles that do not build software.
- team_size: the total number of people when a page states it, for example "a team of 6" or "we are 3 founders".
- founded_year: the year the company was founded or started, as written.
- product_status: idea (only an idea, nothing to use or sign up for), landing (a page about the product, no sign-up), waitlist (a waitlist, early access or beta sign-up), no_code (the product runs on a no-code tool such as Bubble, Softr, Glide or Adalo; name the tool in platform), web_app (people sign in and use it in the browser), mobile_app (an app in the App Store or Google Play).
- uses_ai: true when the product itself uses AI (machine learning, LLMs, GPT, computer vision, speech); quote the line that says so.
- funding_mentions: money the company says it raised: the round as written (pre-seed, seed, angel, grant, accelerator, Series A), the amount as a plain number (1500000 for $1.5M, 2000000 for "2 million"), its ISO currency code, and when, as written. Leave amount null when no amount is written.
- revenue_hints: revenue (a stated revenue, ARR, MRR or sales figure), paying_customers (paying customers, clients or named customer logos), pricing (published prices or paid plans for their product), no_budget (an equity-only or unpaid role, or a stated lack of budget).
- tech_statements: lines about who builds the product: engineering_team (their own engineers or developers), no_technical_team (non-technical founders, or looking for a technical co-founder, CTO or first developer), outsourced (an agency, studio or freelancers build it), no_code (built with a no-code tool).
{% else %}

Leave the startup fields empty: team_members, team_size, founded_year, product_status, uses_ai, funding_mentions, revenue_hints and tech_statements.
{% endif %}
- Respect the list limits: at most 5 decision makers, 6 phones, 4 emails, 12 services, 10 price points, 10 careers roles, 4 languages, 3 sales notes, 12 team members, 3 funding mentions, 3 revenue hints, 3 tech statements.

[user]
Segment: {{ segment_id }}{% if country is defined and country %} ({{ country }}){% endif %}

Business: {{ business_name }}
Website: {{ website }}
{% if context is defined and context %}
Already known from the site's code (do not repeat these unless a page states them):
{{ context | tojson }}
{% endif %}
{% if structured_data is defined and structured_data %}
Structured data found on the site (JSON-LD), for orientation only; quote the page text, not this:
{{ structured_data | tojson }}
{% endif %}
{% if tech_flags is defined and tech_flags %}
Tech detected on the site: {{ tech_flags | tojson }}
{% endif %}

{% for page in pages %}
### PAGE {{ loop.index }}
URL: {{ page.url }}
TEXT:
{{ page.text }}
### END PAGE {{ loop.index }}

{% endfor %}
