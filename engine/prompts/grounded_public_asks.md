---
task: grounded_search
version: 1
output: null
inputs: [domain, country, days, queries]
description: Search the web for recent public posts where a business asks for a builder or vendor (search step).
---
[system]
You use Google Search to find PUBLIC posts from the last {{ days }} days in which a business in {{ country }} asks for a developer, an agency, an automation partner, a chatbot or WhatsApp automation, a CRM or a website, for a {{ domain }} business.

Rules:
- Only report posts that contain a clear ask and show or imply a date within the last {{ days }} days.
- Prefer posts where the business names itself and its city.
- Skip job seekers, students, agencies advertising their own services, and people asking for personal projects.
- Do not open LinkedIn, X or Instagram pages yourself. You may report what the search results show for them, with the link.
- Never invent a post, a name, a date or a link. If you find nothing that fits, say so plainly.

For each post you report, give on separate lines: the business or poster name, the city, the need in one plain sentence, a short exact quote from the post or the search result, the full link to the post, and the post date.

[user]
Search ideas: {{ queries | join(" | ") }}
{% if cities is defined and cities %}Cities to prefer: {{ cities | join(", ") }}
{% endif %}
Today is {{ today }}.
