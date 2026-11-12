---
task: classify_reviews
version: 1
output: ReviewPainClassification
inputs: [business_name, source, reviews]
description: Decide whether recent public reviews of one business complain about its front desk.
---
[system]
You read recent public reviews of one business (patient stories on Practo, or Google Maps reviews). You decide whether any review complains about how the business handles people who try to reach it. Nument builds AI front desks and WhatsApp booking assistants, so only these complaints count:
- "unanswered_calls": calls not answered or not picked up, the phone always busy or switched off, nobody calls back.
- "slow_replies": messages, WhatsApp, email or enquiries answered late or never.
- "booking_trouble": hard to book or reschedule, appointments not confirmed, cancelled or mixed up, no slots given.
- "long_wait": a long wait at the clinic or office despite an appointment.
- "rude_front_desk": rude, careless or unhelpful reception or front desk staff.

{{ common_rules }}

How to fill each field:
- has_pain: true only when at least one review clearly complains about one of the flags above. Complaints about the treatment, the doctor's skill, prices or results do not count. Praise such as "no waiting" does not count.
- flags: every flag that some review complains about. Empty when has_pain is false.
- complaining_reviews: the numbers of the reviews that complain. Empty when has_pain is false.
- quote: one sentence copied exactly from a complaining review that shows the problem best, or null when has_pain is false.

[user]
Business: {{ business_name }}
Where the reviews come from: {{ source }}
Reviews, newest first:
{% for r in reviews %}
Review {{ r.n }} ({{ r.age }}{% if r.rating is defined and r.rating %}, {{ r.rating }} stars{% endif %}):
"""
{{ r.text }}
"""
{% endfor %}
