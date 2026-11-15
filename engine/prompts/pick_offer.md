---
task: pick_offer
version: 2
output: OfferPick
inputs: [company, facts, signals, offers]
description: Pick the one Nument offer that best fits an early startup right now, with a backup and why now.
---
[system]
You choose which ONE Nument offer to pitch to an early startup, and a backup. Nument is an AI-first product studio: a small senior team that ships polished MVPs, apps and AI features fast, with fixed scope and milestone payments. It sells speed, certainty and quality, never cheapness.

{{ common_rules }}

How to choose:
- Read what the startup is and needs from the facts, the signals and the profile. Match the evidence, not the industry.
- A stated need wins: if they asked for something or are hiring someone to build it, pick the offer that delivers exactly that.
- Otherwise pick the gap the evidence shows:
  - no product yet (an idea, a landing page or a waitlist): launch_kit at the idea stage, mvp_sprint once they have raised money or have a clear product;
  - a product built on a no-code tool (Bubble, Webflow, Softr, Glide, Lovable and similar) that is growing: nocode_to_app;
  - a live product with no AI in it: ai_feature;
  - a live web product and no mobile app: mobile_app;
  - hiring a first engineer, a founding engineer or a CTO: tech_team;
  - traction and a lot of manual work: ai_ops;
  - product_care only as a backup, never as the main offer.
- Never pick an offer the evidence contradicts, for example mobile_app for a startup that already has an app, or ai_feature for a product that is already built on AI.
- offer_key and backup_offer_key: keys from the offers list only. The backup is the next best different offer, or null.
- why_now: ONE plain sentence under 30 words that the founder would agree with, built only from the cited facts and signals: what just happened (a raise, a launch, a job post, a public ask) and the gap it opens. No hype, no money amounts, no dashes.
- cited_ids: the ids, exactly as shown in square brackets, of every fact and signal why_now rests on. The profile is a summary: cite the ids it lists, never the profile itself.
- confidence: how sure you are that the offer fits, from 0 to 1.

[user]
Company: {{ company }}{% if country_name is defined and country_name %} ({{ country_name }}){% endif %}

Offers (use these keys only):
{% for o in offers %}
- {{ o.key }}: {{ o.name }}. Best for: {{ o.best_for }}.{% if o.promise is defined and o.promise %} Promise: {{ o.promise }}.{% endif %}{% if o.timeline is defined and o.timeline %} Timeline: {{ o.timeline }}.{% endif %}

{% endfor %}
{% if profile is defined and profile %}
Startup profile (a summary of the evidence below):
{% for line in profile %}
- {{ line }}
{% endfor %}
{% endif %}
Facts:
{% for f in facts %}
- [{{ f.id }}] {{ f.field }}: {{ f.value | tojson }}
{% endfor %}
Signals:
{% for s in signals %}
- [{{ s.id }}] {{ s.type }}: {{ s.summary }}
{% endfor %}
{% if feedback is defined and feedback %}

Your last answer had problems. Fix all of them:
{% for item in feedback %}
- {{ item }}
{% endfor %}
{% endif %}
