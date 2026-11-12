-- 0012_read_performance.sql : faster reads for the web app, with the same rows for every role
--
-- Nothing here changes who can read or write what, or what any view returns. Four kinds of change:
--
-- 1. Row Level Security policies call public.auth_role() and auth.uid() through a sub-select, so Postgres
--    works them out once per query (an InitPlan) instead of once per row. The expressions are otherwise the
--    ones from 0003 and 0011, word for word. Per row, every view row paid for a profiles lookup in each of
--    leads, businesses, scores, signals and contacts.
-- 2. v_primary_contact checks Do not contact with two NOT EXISTS (phone, then email) instead of one with OR.
--    "not (A or B)" is "not A and not B", so the same contacts pass; each check is now a hash anti join or
--    an index lookup instead of comparing every contact with every suppression row.
-- 3. v_leads_caller and v_funnel pick the top signal and the best contact per lead with LATERAL ... LIMIT 1,
--    in the same order as v_top_signal and v_primary_contact (DISTINCT ON keeps the first row of that same
--    order, so the rows and columns are the same). Before, the planner could not estimate the RLS filters,
--    chose nested loops and re-read the whole sorted contact and signal lists once per lead: about 20
--    seconds for one page of 50 leads at 6,000 leads. Now each lead costs two index lookups, and only for the
--    rows a query returns. The column list is unchanged, so v_leads_admin, v_today and v_followups_due,
--    which select from v_leads_caller, stay as they are.
-- 4. Indexes for the filters and sorts the pages use that had none (sequential scans in the plans).
--
-- EXPLAIN (ANALYZE) before and after: docs/perf/0012-explain.md (local Postgres 16, these migrations,
-- synthetic data of 60,000 businesses, 24,000 contacts, 15,000 signals, 6,000 leads, 30,000 activities,
-- read as an admin through RLS). Apply with: cd engine && uv run nlead db migrate.

-- 1. RLS: evaluate the role once per query --------------------------------------------------------------
alter policy profiles_select on public.profiles
  using (user_id = (select auth.uid()) or (select public.auth_role()) = 'admin');

alter policy settings_admin_select on public.settings using ((select public.auth_role()) = 'admin');
alter policy segments_read on public.segments using ((select public.auth_role()) in ('admin','caller','viewer'));

alter policy businesses_read on public.businesses using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy contacts_read   on public.contacts   using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy signals_read    on public.signals    using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy facts_read      on public.facts      using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy scores_read     on public.scores     using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy pages_read      on public.pages      using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy leads_read      on public.leads      using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy activities_read on public.activities using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy feedback_read   on public.feedback   using ((select public.auth_role()) in ('admin','caller','viewer'));
alter policy suppression_read on public.suppression using ((select public.auth_role()) in ('admin','caller'));

alter policy runs_admin   on public.runs          using ((select public.auth_role()) = 'admin');
alter policy costs_admin  on public.costs         using ((select public.auth_role()) = 'admin');
alter policy health_admin on public.source_health using ((select public.auth_role()) = 'admin');

alter policy custom_queries_admin on public.custom_queries
  using ((select public.auth_role()) = 'admin') with check ((select public.auth_role()) = 'admin');
alter policy inbox_admin on public.inbox_posts
  using ((select public.auth_role()) = 'admin') with check ((select public.auth_role()) = 'admin');
alter policy notify_recipients_admin on public.notify_recipients
  using ((select public.auth_role()) = 'admin') with check ((select public.auth_role()) = 'admin');

alter policy saved_views_read on public.saved_views using (user_id = (select auth.uid()) or shared);
alter policy saved_views_own on public.saved_views
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- 2. Best contact per business (the sheets and the engine read it): a cheaper Do not contact check ------
create or replace view public.v_primary_contact with (security_invoker = true) as
select distinct on (c.business_id)
  c.business_id, c.id as contact_id, c.name, c.role, c.phone_e164, c.phone_type,
  c.email, c.source, c.source_url, c.is_decision_maker, c.verified
from public.contacts c
where not c.do_not_contact
  and (c.phone_e164 is not null or c.email is not null)
  and not exists (select 1 from public.suppression su where su.phone_e164 = c.phone_e164)
  and not exists (select 1 from public.suppression su where lower(su.email) = lower(c.email))
order by c.business_id,
         (c.phone_e164 is not null) desc,
         c.is_decision_maker desc,
         (c.phone_type = 'mobile') desc,
         c.verified desc,
         (c.source = 'website') desc,
         c.created_at;

-- 3. One row per lead with its top signal and best contact, by index ------------------------------------
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
-- Same rule and order as v_top_signal.
left join lateral (
  select g.type, g.quote, g.url, g.observed_at
  from public.signals g
  where g.business_id = l.business_id and g.expires_at > now()
  order by g.points desc, g.observed_at desc
  limit 1
) ts on true
-- Same rule and order as v_primary_contact.
left join lateral (
  select c.name, c.role, c.phone_e164, c.phone_type, c.source, c.email
  from public.contacts c
  where c.business_id = l.business_id
    and not c.do_not_contact
    and (c.phone_e164 is not null or c.email is not null)
    and not exists (select 1 from public.suppression su where su.phone_e164 = c.phone_e164)
    and not exists (select 1 from public.suppression su where lower(su.email) = lower(c.email))
  order by (c.phone_e164 is not null) desc,
           c.is_decision_maker desc,
           (c.phone_type = 'mobile') desc,
           c.verified desc,
           (c.source = 'website') desc,
           c.created_at
  limit 1
) pc on true;

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
-- Same rule and order as v_top_signal.
left join lateral (
  select g.type
  from public.signals g
  where g.business_id = l.business_id and g.expires_at > now()
  order by g.points desc, g.observed_at desc
  limit 1
) ts on true;

-- 4. Indexes ---------------------------------------------------------------------------------------------
-- The best contact per lead (above): contacts by business. The existing unique index covers only rows
-- with a phone.
create index if not exists contacts_business_idx on public.contacts (business_id);
-- Leads list default sort exactly as the app asks for it (Added, newest first, then id), so a page of 50
-- reads 50 index entries and looks up 50 signals and contacts. Also the Insights and Engine date ranges.
create index if not exists leads_created_idx on public.leads (created_at desc nulls last, id);
-- Pipeline board order and the Leads "Last activity" sort, the same way.
create index if not exists leads_last_activity_idx on public.leads (last_activity_at desc nulls last, id);
-- Insights "researched" count and the Engine page "researched yesterday" per segment.
create index if not exists businesses_researched_idx on public.businesses (researched_at) where researched_at is not null;
