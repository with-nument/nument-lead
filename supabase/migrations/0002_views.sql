-- 0002_views.sql : read models for the app, the sheets and reports

-- Best contact per business: has a phone, decision maker, mobile, verified, own website.
-- Skips do-not-contact rows and anything in suppression.
create or replace view public.v_primary_contact with (security_invoker = true) as
select distinct on (c.business_id)
  c.business_id, c.id as contact_id, c.name, c.role, c.phone_e164, c.phone_type,
  c.email, c.source, c.source_url, c.is_decision_maker, c.verified
from public.contacts c
where not c.do_not_contact
  and (c.phone_e164 is not null or c.email is not null)
  and not exists (select 1 from public.suppression su
                  where su.phone_e164 = c.phone_e164 or lower(su.email) = lower(c.email))
order by c.business_id,
         (c.phone_e164 is not null) desc,
         c.is_decision_maker desc,
         (c.phone_type = 'mobile') desc,
         c.verified desc,
         (c.source = 'website') desc,
         c.created_at;

-- Strongest active signal per business (same order as the sheet view in Step 13).
create or replace view public.v_top_signal with (security_invoker = true) as
select distinct on (g.business_id)
  g.business_id, g.id as signal_id, g.type, g.category, g.points,
  g.quote, g.url, g.observed_at, g.expires_at
from public.signals g
where g.expires_at > now()
order by g.business_id, g.points desc, g.observed_at desc;

-- Latest verified fact per business and field (lead page evidence, message writer).
create or replace view public.v_verified_facts with (security_invoker = true) as
select distinct on (f.business_id, f.field) f.*
from public.facts f
where f.verified
order by f.business_id, f.field, f.created_at desc;

-- Every lead column except deal_value_inr, plus business, score, top signal and best contact.
-- Callers and viewers read leads only through this view.
create or replace view public.v_leads_caller with (security_invoker = true) as
select
  l.id, l.business_id, l.segment_id, l.score_id, l.grade, l.pitch_mode, l.test_group, l.angle,
  l.channel, l.message, l.message_alt, l.email_subject, l.email_body, l.followup_d3, l.followup_d7,
  l.message_model, l.message_check_score, l.stage, l.owner_id, l.wa_at, l.call_at, l.d3_at, l.d7_at,
  l.meeting_at, l.next_step, l.due_at, l.skipped_until, l.regen_requested_at, l.notes,
  l.created_at, l.updated_at, l.last_activity_at,
  b.name, b.city, b.locality, b.country, b.website, b.web_domain, b.category, b.subcategory,
  sc.total, sc.judge_note,
  ts.type as top_signal_type, ts.quote as top_signal_quote, ts.url as top_signal_url,
  ts.observed_at as top_signal_at,
  pc.name as contact_name, pc.role as contact_role, pc.phone_e164, pc.phone_type,
  pc.source as phone_source, pc.email
from public.leads l
join public.businesses b on b.id = l.business_id
left join public.scores sc on sc.id = l.score_id
left join public.v_top_signal ts on ts.business_id = l.business_id
left join public.v_primary_contact pc on pc.business_id = l.business_id;

-- The same plus money, for admins. NOT security_invoker: it runs with its owner's rights so it
-- can read deal_value_inr, and it returns rows only when the person asking is an admin.
create or replace view public.v_leads_admin as
select v.*, l.deal_value_inr
from public.v_leads_caller v
join public.leads l on l.id = v.id
where public.auth_role() = 'admin';

-- The same plus money, for the engine (service role) only. Revoked from app users in 0003.
create or replace view public.v_pipeline with (security_invoker = true) as
select v.*, l.deal_value_inr
from public.v_leads_caller v
join public.leads l on l.id = v.id;

-- Today's send list (Step 15 Today page): new A and B leads, reachable, not skipped, best first.
create or replace view public.v_today with (security_invoker = true) as
select v.id as lead_id, v.business_id, v.name as company, v.city, v.country, v.segment_id,
       v.grade, v.total, v.pitch_mode, v.angle, v.test_group, v.channel,
       v.top_signal_type, v.top_signal_quote, v.top_signal_url, v.top_signal_at,
       v.contact_name, v.contact_role, v.phone_e164, v.phone_type, v.phone_source, v.email,
       v.message, v.message_alt, v.email_subject, v.email_body, v.created_at
from public.v_leads_caller v
where v.stage = 'new'
  and v.grade in ('A','B')
  and (v.skipped_until is null or v.skipped_until <= now())
  and (v.phone_e164 is not null or v.channel <> 'whatsapp')
  and not exists (select 1 from public.suppression su where su.web_domain = v.web_domain)
order by v.grade, v.total desc nulls last, v.created_at;

-- Day 3 and day 7 follow-ups due today or earlier (Step 15 Today page).
-- Only leads still at 'contacted' (no reply yet). Day 7 waits until day 3 was sent.
create or replace view public.v_followups_due with (security_invoker = true) as
select v.id as lead_id, v.name as company, v.segment_id, v.grade, v.contact_name, v.phone_e164,
       f.which, f.followup_text, f.due_on
from public.v_leads_caller v
cross join lateral (values
    ('d3', v.followup_d3, v.wa_at + 3, v.d3_at is null),
    ('d7', v.followup_d7, greatest(v.wa_at + 7, v.d3_at + 3), v.d3_at is not null and v.d7_at is null)
  ) as f(which, followup_text, due_on, is_open)
where v.stage = 'contacted'
  and v.wa_at is not null
  and f.is_open
  and f.due_on <= (now() at time zone 'Asia/Kolkata')::date
  and (v.skipped_until is null or v.skipped_until <= now())
order by f.due_on, v.grade, v.total desc nulls last;

-- One row per lead with the furthest stage it ever reached (Step 15 Insights).
-- History comes from stage_change activities, so a lead that later closed still counts.
create or replace view public.v_funnel with (security_invoker = true) as
with ranks(stage, rnk) as (
  values ('new', 0), ('contacted', 1), ('talking', 2), ('discovery_booked', 3),
         ('discovery_done', 3), ('proposal_sent', 4), ('won', 5), ('retainer', 5)
),
reached as (
  select l.id as lead_id,
         greatest(coalesce(max(r_now.rnk), 0), coalesce(max(r_hist.rnk), 0)) as max_rnk
  from public.leads l
  left join ranks r_now on r_now.stage = l.stage
  left join public.activities a on a.lead_id = l.id and a.type = 'stage_change'
  left join ranks r_hist on r_hist.stage = a.payload ->> 'to'
  group by l.id
)
select l.id as lead_id, l.segment_id, b.country, l.pitch_mode, l.angle, l.test_group, l.grade,
       ts.type as top_signal_type,
       (l.created_at at time zone 'Asia/Kolkata')::date as created_on,
       (r.max_rnk >= 1 or l.wa_at is not null) as reached_contacted,
       r.max_rnk >= 2 as reached_talking,
       r.max_rnk >= 3 as reached_discovery,
       r.max_rnk >= 4 as reached_proposal,
       r.max_rnk >= 5 as reached_won
from public.leads l
join public.businesses b on b.id = l.business_id
join reached r on r.lead_id = l.id
left join public.v_top_signal ts on ts.business_id = l.business_id;

-- This week's numbers (week starts Monday, IST). No money here.
create or replace view public.v_kpis_week with (security_invoker = true) as
with b as (
  select date_trunc('week', now() at time zone 'Asia/Kolkata')::date as week_start,
         (now() at time zone 'Asia/Kolkata')::date as today
)
select
  count(*) filter (where l.wa_at >= b.week_start)                                   as contacted_this_week,
  count(*) filter (where l.stage in ('talking','discovery_booked','discovery_done',
                                     'proposal_sent','won','retainer'))              as conversations,
  count(*) filter (where l.stage in ('discovery_booked','discovery_done',
                                     'proposal_sent','won','retainer'))              as discovery_calls,
  count(*) filter (where l.stage in ('proposal_sent','won','retainer'))              as proposals,
  count(*) filter (where l.stage in ('won','retainer'))                              as won,
  count(*) filter (where l.due_at < b.today and l.stage not in
                   ('won','retainer','lost','not_now','not_a_fit','wrong_contact'))  as overdue,
  count(*) filter (where l.stage = 'new')                                           as new_waiting
from public.leads l cross join b;

-- Daily AI and API spend in IST days. Same columns as Step 19.4.
create or replace view public.v_costs_daily with (security_invoker = true) as
select (at at time zone 'Asia/Kolkata')::date as day, provider, task,
       sum(calls) as calls, sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens,
       sum(usd)::numeric(12,4) as usd, sum(inr)::numeric(12,2) as inr
from public.costs
group by 1, 2, 3;

-- Source health with a computed status for the Engine page.
create or replace view public.v_source_health with (security_invoker = true) as
select h.*,
  case
    when not h.enabled then 'disabled'
    when h.blocked_until is not null and h.blocked_until > now() then 'blocked'
    when h.last_error_at is not null and (h.last_ok_at is null or h.last_error_at > h.last_ok_at) then 'error'
    when h.last_ok_at is null or h.last_ok_at < now() - interval '3 days' then 'stale'
    else 'ok'
  end as health
from public.source_health h;

-- Database size in MB (`nlead health` and the Engine page, 2.13).
create or replace function public.db_size_mb() returns numeric
language sql stable security definer set search_path = public as $$
  select round(pg_database_size(current_database()) / 1024.0 / 1024.0, 1)
$$;
