-- 0024_page_reads.sql : one database call per page (web speed, 15 Nov 2026)
--
-- The web app runs on Render in Singapore with about a tenth of a CPU; the database is in Mumbai, so every
-- request costs 60 ms or more before any work, and adding up rows in JavaScript is slow. Today made eleven
-- requests (six counts, the send list, the follow-ups and their cities, the month's wins and their money), the
-- lead page five, the board up to eight (the money in batches of 150 ids) and the Insights page sent ten
-- thousand rows to be counted in JavaScript. Each page now makes one call to one function here, and the
-- database does the counting:
--
--   home_summary(list_limit)                    Today: the counts, the send list, the follow-ups due (with city
--                                               and phone type) and, for admins, the money won this month
--   nav_counts()                                small numbers for the navigation
--   lead_detail(lead_id, include_unverified)    the lead page: lead, business, contacts, signals, facts, latest
--                                               score, pages, timeline, feedback, the Do not contact check and,
--                                               for admins, the money
--   deals_board(filters, max_per_stage,         the pipeline: the open stages (contacted to proposal sent) and a
--               closed_per_stage)               count for every stage; closed cards only when asked for
--   leads_page(filters, page, page_size)        one page of leads, the total, the cities for the filter and the
--                                               saved views
--   search_leads(q, max)                        leads by business name or website, typo tolerant (pg_trgm)
--   insights_summary(from_ts, to_ts, filters)   the funnel, the groups, lead quality and, for admins, the costs
--   engine_counts()                             the live part of the Engine page
--
-- Who sees what does not change. Every function but search_leads runs as the signed-in user (security invoker),
-- so Row Level Security applies to every table and view exactly as it did to the requests they replace
-- (search_leads checks the role itself, see there). Money is read only
-- through v_leads_admin, which is empty for anyone but an admin; nothing here reads leads.deal_value_inr or the
-- other money columns directly. Unverified facts and the cost numbers are admin-only, as on the pages. The rules
-- each page used (which leads are on Today, which follow-ups are due, what counts as overdue, how the funnel
-- counts a lead) are the views' rules: the functions read v_today, v_followups_due and v_leads_caller rather than
-- copying them. The functions are written as text (not BEGIN ATOMIC), so a later migration can still drop and
-- rebuild those views.
--
-- Every function returns one jsonb value (never a set of rows), so the PostgREST row limit does not apply: the
-- old board read at most 1,000 rows across every stage, newest first, and once enough leads had closed, real
-- deals fell off the end.
--
-- Also: trigram indexes on businesses.name and businesses.web_domain for search_leads, an index for "sent this
-- week" and one for the leads of a business.

create extension if not exists pg_trgm with schema extensions;

create index if not exists businesses_name_trgm on public.businesses using gin (name extensions.gin_trgm_ops);
create index if not exists businesses_web_domain_trgm on public.businesses using gin (web_domain extensions.gin_trgm_ops);
-- Today's "Sent this week" counts first messages by date; until now that was a scan of every lead.
create index if not exists leads_wa_at_idx on public.leads (wa_at) where wa_at is not null;
-- Leads of a business (search starts from businesses). Only the partial "one open lead" index existed.
create index if not exists leads_business_idx on public.leads (business_id);

-- =========================================================================================================
-- Today
-- =========================================================================================================
-- counts       ready (rows of v_today), contacted_this_week (first message on or after Monday, India time),
--              talking, discovery (booked or done), proposals, overdue (due before today and still open)
-- won_this_month_inr   admins only, else null: deal values (rupees) of leads that moved to Won or Retainer since
--              the 1st of this month (India time) and are still there
-- send         the first list_limit rows of v_today, best first (grade, score, oldest)
-- followups    the first list_limit rows of v_followups_due, earliest first, with the business's city and the
--              type of the shown phone (WhatsApp is for mobiles)
create or replace function public.home_summary(list_limit integer default 100)
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with p as (
    select (now() at time zone 'Asia/Kolkata')::date as today,
           date_trunc('week', now() at time zone 'Asia/Kolkata')::date as week_start,
           date_trunc('month', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata' as month_start,
           (select public.auth_role()) as role
  ),
  -- Each v_today row costs two index lookups (top signal and best contact): work the list out once, keep only
  -- what the count and the order need, then read the full rows of the first page only. v_today is a sorted
  -- view, which Postgres never merges into a bigger query, so those rows come from v_leads_caller by id (the
  -- same columns v_today copies, under other names) and cost an index lookup each.
  ready as materialized (
    select t.lead_id, t.grade, t.total, t.created_at from public.v_today t
  ),
  first_ids as (
    select r.lead_id from ready r
    order by r.grade, r.total desc nulls last, r.created_at, r.lead_id
    limit least(greatest(coalesce(list_limit, 100), 1), 500)
  ),
  send as (
    select v.id as lead_id, v.name as company, v.city, v.country, v.segment_id, v.grade, v.total, v.channel,
           v.top_signal_type, v.top_signal_quote, v.top_signal_url, v.top_signal_at, v.contact_name, v.contact_role,
           v.phone_e164, v.phone_type, v.phone_source, v.email, v.email_subject, v.email_body, v.message, v.created_at
    from public.v_leads_caller v
    where v.id in (select f.lead_id from first_ids f)
  ),
  due as (
    select f.lead_id, f.company, f.segment_id, f.grade, f.contact_name, f.phone_e164, f.which, f.followup_text, f.due_on
    from public.v_followups_due f
    where f.which in ('d3', 'd7') and f.due_on is not null
    order by f.due_on, f.grade, f.lead_id, f.which
    limit least(greatest(coalesce(list_limit, 100), 1), 500)
  )
  select jsonb_build_object(
    'counts', jsonb_build_object(
      'ready', (select count(*) from ready),
      'contacted_this_week', (select count(*) from public.leads l, p where l.wa_at >= p.week_start),
      'talking', (select count(*) from public.leads l where l.stage = 'talking'),
      'discovery', (select count(*) from public.leads l where l.stage in ('discovery_booked', 'discovery_done')),
      'proposals', (select count(*) from public.leads l where l.stage = 'proposal_sent'),
      'overdue', (select count(*) from public.leads l, p
                  where l.due_at < p.today
                    and l.stage not in ('won', 'retainer', 'lost', 'not_now', 'not_a_fit', 'wrong_contact'))
    ),
    'won_this_month_inr', (
      select case when p.role = 'admin' then coalesce((
        select sum(a.deal_value_inr)
        from public.v_leads_admin a
        where a.stage in ('won', 'retainer')
          and a.id in (select x.lead_id from public.activities x
                       where x.type = 'stage_change' and x.at >= p.month_start
                         and x.payload ->> 'to' in ('won', 'retainer'))
      ), 0) end
      from p
    ),
    'send', coalesce((
      select jsonb_agg(jsonb_build_object(
               'lead_id', s.lead_id, 'company', coalesce(s.company, 'Unnamed business'), 'city', s.city,
               'country', s.country, 'segment_id', s.segment_id, 'grade', s.grade, 'total', s.total,
               'channel', s.channel, 'top_signal_type', s.top_signal_type, 'top_signal_quote', s.top_signal_quote,
               'top_signal_url', s.top_signal_url, 'top_signal_at', s.top_signal_at,
               'contact_name', s.contact_name, 'contact_role', s.contact_role, 'phone_e164', s.phone_e164,
               'phone_type', s.phone_type, 'phone_source', s.phone_source, 'email', s.email,
               'email_subject', s.email_subject, 'email_body', s.email_body, 'message', s.message)
             order by s.grade, s.total desc nulls last, s.created_at, s.lead_id)
      from send s
    ), '[]'::jsonb),
    'followups', coalesce((
      select jsonb_agg(jsonb_build_object(
               'lead_id', d.lead_id, 'company', coalesce(d.company, 'Unnamed business'),
               'segment_id', d.segment_id, 'grade', d.grade, 'contact_name', d.contact_name,
               'phone_e164', d.phone_e164, 'which', d.which, 'followup_text', d.followup_text,
               'due_on', d.due_on, 'city', x.city, 'phone_type', x.phone_type)
             order by d.due_on, d.grade, d.lead_id, d.which)
      from due d
      -- The business's city, and the type of the contact that owns the shown phone (unique per business).
      left join lateral (
        select b.city,
               (select c.phone_type from public.contacts c
                 where c.business_id = l.business_id and c.phone_e164 = d.phone_e164
                 limit 1) as phone_type
        from public.leads l
        join public.businesses b on b.id = l.business_id
        where l.id = d.lead_id
      ) x on true
    ), '[]'::jsonb)
  )
$$;

-- Small numbers for the navigation, the same for every role (Row Level Security decides; the inbox is
-- admin-only, so everyone else gets 0 there).
create or replace function public.nav_counts()
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  select jsonb_build_object(
    'ready', (select count(*) from public.v_today),
    'followups_due', (select count(*) from public.v_followups_due),
    'overdue', (select count(*) from public.leads l
                where l.due_at < (now() at time zone 'Asia/Kolkata')::date
                  and l.stage not in ('won', 'retainer', 'lost', 'not_now', 'not_a_fit', 'wrong_contact')),
    'deals', (select count(*) from public.leads l
              where l.stage in ('talking', 'discovery_booked', 'discovery_done', 'proposal_sent')),
    'inbox_new', (select count(*) from public.inbox_posts i where i.status = 'new')
  )
$$;

-- =========================================================================================================
-- The lead page
-- =========================================================================================================
-- null when the lead does not exist or is not visible to this user. Otherwise:
--   lead               every v_leads_caller column, plus lost_reason (meaningful only while Lost or Not now)
--   business           name, website, web_domain, address, place_id, branches_count, staff_count, rating,
--                      review_count
--   contacts           up to 50, decision makers first, then oldest first
--   suppressed_phones  which of those contacts' numbers are on Do not contact (empty for viewers, who cannot
--                      read the list)
--   signals            up to 50, newest first; facts up to 300, newest first, verified only unless an admin
--                      asks for unverified ones; score the latest one or null; pages up to 20, newest first
--   activities         the timeline, up to 100, newest first; feedback every vote, newest first
--   money              admins only, else null: {deal, retainer, currency}, through v_leads_admin
create or replace function public.lead_detail(lead_id uuid, include_unverified boolean default false)
returns jsonb
language plpgsql
stable
set search_path = public, extensions
as $$
declare
  v_role text := (select public.auth_role());
  v_lead jsonb;
  v_business uuid;
  v_unverified boolean;
  v_contacts jsonb;
  v_phones text[];
begin
  select to_jsonb(v) || jsonb_build_object('lost_reason', l.lost_reason), v.business_id
    into v_lead, v_business
    from public.v_leads_caller v
    join public.leads l on l.id = v.id
   where v.id = lead_detail.lead_id;
  if v_lead is null then
    return null;
  end if;
  v_unverified := coalesce(lead_detail.include_unverified, false) and v_role = 'admin';

  select coalesce(jsonb_agg(jsonb_build_object(
           'id', c.id, 'name', c.name, 'role', c.role, 'phone_e164', c.phone_e164, 'phone_type', c.phone_type,
           'email', c.email, 'source', c.source, 'source_url', c.source_url, 'quote', c.quote,
           'is_decision_maker', c.is_decision_maker, 'verified', c.verified, 'do_not_contact', c.do_not_contact,
           'created_at', c.created_at, 'line', c.line, 'line_why', c.line_why)
           order by c.is_decision_maker desc, c.created_at, c.id), '[]'::jsonb),
         coalesce(array_agg(c.phone_e164) filter (where c.phone_e164 is not null), '{}')
    into v_contacts, v_phones
    from (select c0.id, c0.name, c0.role, c0.phone_e164, c0.phone_type, c0.email, c0.source, c0.source_url,
                 c0.quote, c0.is_decision_maker, c0.verified, c0.do_not_contact, c0.created_at, c0.line, c0.line_why
            from public.contacts c0
           where c0.business_id = v_business
           order by c0.is_decision_maker desc, c0.created_at, c0.id
           limit 50) c;

  return jsonb_build_object(
    'lead', v_lead,
    'business', (
      select jsonb_build_object(
               'name', b.name, 'website', b.website, 'web_domain', b.web_domain, 'address', b.address,
               'place_id', b.place_id, 'branches_count', b.branches_count, 'staff_count', b.staff_count,
               'rating', b.rating, 'review_count', b.review_count)
      from public.businesses b where b.id = v_business
    ),
    'contacts', v_contacts,
    'suppressed_phones', coalesce((
      select jsonb_agg(distinct s.phone_e164) from public.suppression s where s.phone_e164 = any(v_phones)
    ), '[]'::jsonb),
    'signals', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', g.id, 'type', g.type, 'category', g.category, 'points', g.points,
               'observed_at', g.observed_at, 'expires_at', g.expires_at, 'source', g.source, 'url', g.url,
               'quote', g.quote)
             order by g.observed_at desc, g.id)
      from (select g0.id, g0.type, g0.category, g0.points, g0.observed_at, g0.expires_at, g0.source, g0.url, g0.quote
              from public.signals g0
             where g0.business_id = v_business
             order by g0.observed_at desc, g0.id
             limit 50) g
    ), '[]'::jsonb),
    'facts', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', f.id, 'field', f.field, 'value', f.value, 'quote', f.quote, 'url', f.url, 'model', f.model,
               'verified', f.verified, 'created_at', f.created_at)
             order by f.created_at desc, f.id)
      from (select f0.id, f0.field, f0.value, f0.quote, f0.url, f0.model, f0.verified, f0.created_at
              from public.facts f0
             where f0.business_id = v_business and (v_unverified or f0.verified)
             order by f0.created_at desc, f0.id
             limit 300) f
    ), '[]'::jsonb),
    'score', (
      select jsonb_build_object(
               'fit', s.fit, 'can_pay', s.can_pay, 'intent', s.intent, 'reach', s.reach, 'total', s.total,
               'grade', s.grade, 'pitch_mode', s.pitch_mode, 'reasons', s.reasons, 'judge_grade', s.judge_grade,
               'judge_note', s.judge_note, 'judge_model', s.judge_model, 'version', s.version,
               'computed_at', s.computed_at)
      from public.scores s
      where s.business_id = v_business
      order by s.computed_at desc, s.id
      limit 1
    ),
    'pages', coalesce((
      select jsonb_agg(jsonb_build_object('id', pg.id, 'url', pg.url, 'title', pg.title, 'fetched_at', pg.fetched_at)
             order by pg.fetched_at desc, pg.id)
      from (select p0.id, p0.url, p0.title, p0.fetched_at
              from public.pages p0
             where p0.business_id = v_business
             order by p0.fetched_at desc, p0.id
             limit 20) pg
    ), '[]'::jsonb),
    'activities', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', a.id, 'type', a.type, 'source', a.source, 'at', a.at, 'user_id', a.user_id, 'payload', a.payload)
             order by a.at desc, a.id)
      from (select a0.id, a0.type, a0.source, a0.at, a0.user_id, a0.payload
              from public.activities a0
             where a0.lead_id = lead_detail.lead_id
             order by a0.at desc, a0.id
             limit 100) a
    ), '[]'::jsonb),
    'feedback', coalesce((
      select jsonb_agg(jsonb_build_object('id', fb.id, 'user_id', fb.user_id, 'rating', fb.rating, 'reason', fb.reason,
                                          'at', fb.at)
             order by fb.at desc, fb.id)
      from public.feedback fb
      where fb.lead_id = lead_detail.lead_id
    ), '[]'::jsonb),
    'money', case when v_role = 'admin' then (
      select jsonb_build_object('deal', m.deal_value_inr, 'retainer', m.retainer_monthly_value,
                                'currency', m.deal_currency)
      from public.v_leads_admin m
      where m.id = lead_detail.lead_id
    ) end
  );
end;
$$;

-- =========================================================================================================
-- The pipeline
-- =========================================================================================================
-- filters: {"seg": "clinics-in", "country": "in", "owner": "me" | "none" | <user id>, "overdue": true}
-- cards    every lead in an open stage (contacted, talking, discovery booked or done, proposal sent), at most
--          max_per_stage per stage, most recently active first; plus up to closed_per_stage per closed stage
--          (0 by default). Admins also get deal_value_inr, retainer_monthly_value and deal_currency on the cards
--          that have a deal value or a retainer (a card without them has no money keys).
-- counts   leads per stage for every stage after New, with the same filters, however many cards came back
create or replace function public.deals_board(
  filters jsonb default '{}'::jsonb,
  max_per_stage integer default 500,
  closed_per_stage integer default 0
)
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with p as (
    select (now() at time zone 'Asia/Kolkata')::date as today,
           nullif(btrim(coalesce(filters, '{}'::jsonb) ->> 'seg'), '') as seg,
           nullif(btrim(coalesce(filters, '{}'::jsonb) ->> 'country'), '') as country,
           lower(nullif(btrim(coalesce(filters, '{}'::jsonb) ->> 'owner'), '')) as owner,
           coalesce((coalesce(filters, '{}'::jsonb) ->> 'overdue') in ('true', '1'), false) as overdue,
           least(greatest(coalesce(max_per_stage, 500), 0), 2000) as open_cap,
           least(greatest(coalesce(closed_per_stage, 0), 0), 500) as closed_cap,
           (select public.auth_role()) as role,
           (select auth.uid()) as me
  ),
  -- Straight from leads and businesses: one row per lead, the same rows as v_leads_caller, without its contact
  -- and signal lookups (a card shows neither).
  base as (
    select l.id, b.name, b.city, l.grade, l.stage, l.next_step, l.due_at, l.owner_id, l.segment_id, b.country,
           l.last_activity_at,
           l.stage in ('contacted', 'talking', 'discovery_booked', 'discovery_done', 'proposal_sent') as is_open
    from public.leads l
    join public.businesses b on b.id = l.business_id
    cross join p
    where l.stage <> 'new'
      and (p.seg is null or l.segment_id = p.seg)
      and (p.country is null or b.country = p.country)
      and (p.owner is null
           or (p.owner = 'me' and l.owner_id = p.me)
           or (p.owner = 'none' and l.owner_id is null)
           or (p.owner not in ('me', 'none') and l.owner_id::text = p.owner))
      and (not p.overdue
           or (l.due_at < p.today
               and l.stage not in ('won', 'retainer', 'lost', 'not_now', 'not_a_fit', 'wrong_contact')))
  ),
  cards as (
    select r.*
    from (select base.*,
                 row_number() over (partition by base.stage order by base.last_activity_at desc, base.id) as rn
            from base) r
    cross join p
    where r.rn <= case when r.is_open then p.open_cap else p.closed_cap end
  ),
  -- Worked out once (an inlined join could re-read the admin view for every card), and only for cards with a
  -- deal value or a retainer: the admin view looks up a contact and a signal for every row it returns.
  money as materialized (
    select m.id, m.deal_value_inr, m.retainer_monthly_value, m.deal_currency
    from public.v_leads_admin m
    where (select p.role from p) = 'admin'
      and m.id in (select c.id from cards c)
      and (m.deal_value_inr is not null or m.retainer_monthly_value is not null)
  )
  select jsonb_build_object(
    'cards', coalesce((
      select jsonb_agg(
               jsonb_build_object(
                 'id', c.id, 'name', coalesce(c.name, 'Unnamed business'), 'city', c.city, 'grade', c.grade,
                 'stage', c.stage, 'next_step', c.next_step, 'due_at', c.due_at, 'owner_id', c.owner_id,
                 'segment_id', c.segment_id, 'country', c.country, 'last_activity_at', c.last_activity_at)
               || case when m.id is null then '{}'::jsonb
                       else jsonb_build_object('deal_value_inr', m.deal_value_inr,
                                               'retainer_monthly_value', m.retainer_monthly_value,
                                               'deal_currency', m.deal_currency) end
               order by c.last_activity_at desc, c.id)
      from cards c
      left join money m on m.id = c.id
    ), '[]'::jsonb),
    'counts', coalesce((
      select jsonb_object_agg(s.stage, s.n) from (select b.stage, count(*) as n from base b group by b.stage) s
    ), '{}'::jsonb),
    'open_stages', '["contacted", "talking", "discovery_booked", "discovery_done", "proposal_sent"]'::jsonb,
    'max_per_stage', (select p.open_cap from p),
    'closed_per_stage', (select p.closed_cap from p)
  )
$$;

-- =========================================================================================================
-- The Leads page
-- =========================================================================================================
-- filters: the Leads page URL filters (web/src/lib/leads-filters.ts), as JSON:
--   {"q": text, "seg": [..], "country": [..], "city": [..], "grade": [..], "signal": [..], "stage": [..],
--    "pitch": [..], "mobile": bool, "overdue": bool, "owner": "me" | "none" | <user id>,
--    "from": "YYYY-MM-DD", "to": "YYYY-MM-DD" (India days, both included),
--    "sort": created | score | company | grade | stage | activity | due, "dir": asc | desc}
-- rows     one page of v_leads_caller rows (the list columns), sorted with empty values last, then by id;
--          admins also get deal_value_inr (through v_leads_admin)
-- total    how many leads match. Without filters it is a plain count of leads (v_leads_caller has one row per
--          lead), so the list never pays for the contact and signal lookups of rows it does not show.
-- cities   every city that has a lead (in the chosen countries), for the filter
-- views    saved views: the user's own and the shared ones, with mine = true for the user's own
create or replace function public.leads_page(filters jsonb default '{}'::jsonb, page integer default 1,
                                             page_size integer default 50)
returns jsonb
language plpgsql
stable
set search_path = public, extensions
as $$
declare
  f jsonb := coalesce(leads_page.filters, '{}'::jsonb);
  v_role text := (select public.auth_role());
  v_me uuid := (select auth.uid());
  v_today date := (now() at time zone 'Asia/Kolkata')::date;
  v_size integer := least(greatest(coalesce(leads_page.page_size, 50), 1), 200);
  v_page integer := least(greatest(coalesce(leads_page.page, 1), 1), 10000);
  v_seg text[];
  v_country text[];
  v_city text[];
  v_grade text[];
  v_stage text[];
  v_pitch text[];
  v_signal text[];
  v_mobile boolean := coalesce((f ->> 'mobile') in ('true', '1'), false);
  v_overdue boolean := coalesce((f ->> 'overdue') in ('true', '1'), false);
  v_owner text := lower(nullif(btrim(f ->> 'owner'), ''));
  v_from timestamptz;
  v_to timestamptz;
  v_q text;
  v_like text;
  v_phone_like text;
  v_col text;
  v_dir text;
  v_where text := 'true';
  v_needs_view boolean := false;
  v_source text;
  v_rows jsonb;
  v_ids uuid[];
  v_money jsonb;
  v_total bigint;
begin
  -- Lists: a JSON array of strings, anything else means "no filter".
  select array_agg(distinct x) into v_seg
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'seg') = 'array' then f -> 'seg' else '[]' end) x;
  select array_agg(distinct x) into v_country
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'country') = 'array' then f -> 'country' else '[]' end) x;
  select array_agg(distinct x) into v_city
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'city') = 'array' then f -> 'city' else '[]' end) x;
  select array_agg(distinct x) into v_grade
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'grade') = 'array' then f -> 'grade' else '[]' end) x;
  select array_agg(distinct x) into v_stage
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'stage') = 'array' then f -> 'stage' else '[]' end) x;
  select array_agg(distinct x) into v_pitch
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'pitch') = 'array' then f -> 'pitch' else '[]' end) x;
  select array_agg(distinct x) into v_signal
    from jsonb_array_elements_text(case when jsonb_typeof(f -> 'signal') = 'array' then f -> 'signal' else '[]' end) x;

  -- India days, both included: from midnight of "from" to midnight after "to". A bad date means no filter.
  begin
    if f ->> 'from' ~ '^\d{4}-\d{2}-\d{2}$' then
      v_from := ((f ->> 'from')::date)::timestamp at time zone 'Asia/Kolkata';
    end if;
  exception when others then
    v_from := null;
  end;
  begin
    if f ->> 'to' ~ '^\d{4}-\d{2}-\d{2}$' then
      v_to := ((f ->> 'to')::date + 1)::timestamp at time zone 'Asia/Kolkata';
    end if;
  exception when others then
    v_to := null;
  end;

  -- Free text as the app has always searched it: the characters that broke the old PostgREST filter become
  -- spaces, then name or website contains it, or the phone contains its digits (4 or more).
  v_q := nullif(btrim(regexp_replace(translate(left(btrim(coalesce(f ->> 'q', '')), 80), ',()"''*%\:', '         '),
                                     '\s+', ' ', 'g')), '');
  if v_q is not null then
    v_like := '%' || v_q || '%';
    if length(regexp_replace(v_q, '\D', '', 'g')) >= 4 then
      v_phone_like := '%' || regexp_replace(v_q, '\D', '', 'g') || '%';
    end if;
  end if;

  -- The conditions, only for the filters in use. Values are always bound parameters ($1 to $14).
  if v_seg is not null then v_where := v_where || ' and v.segment_id = any($1)'; end if;
  if v_country is not null then v_where := v_where || ' and v.country = any($2)'; end if;
  if v_city is not null then v_where := v_where || ' and v.city = any($3)'; end if;
  if v_grade is not null then v_where := v_where || ' and v.grade = any($4)'; end if;
  if v_stage is not null then v_where := v_where || ' and v.stage = any($5)'; end if;
  if v_pitch is not null then v_where := v_where || ' and v.pitch_mode = any($6)'; end if;
  if v_signal is not null then
    v_where := v_where || ' and v.top_signal_type = any($7)';
    v_needs_view := true;
  end if;
  if v_mobile then
    v_where := v_where || ' and v.phone_type = ''mobile''';
    v_needs_view := true;
  end if;
  if v_owner = 'me' then
    v_where := v_where || ' and v.owner_id = $8';
  elsif v_owner = 'none' then
    v_where := v_where || ' and v.owner_id is null';
  elsif v_owner ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    v_where := v_where || ' and v.owner_id = $9::uuid';
  end if;
  if v_overdue then
    v_where := v_where || ' and v.due_at < $10 and v.stage not in '
                       || '(''won'', ''retainer'', ''lost'', ''not_now'', ''not_a_fit'', ''wrong_contact'')';
  end if;
  if v_from is not null then v_where := v_where || ' and v.created_at >= $11'; end if;
  if v_to is not null then v_where := v_where || ' and v.created_at < $12'; end if;
  if v_like is not null then
    if v_phone_like is not null then
      v_where := v_where || ' and (v.name ilike $13 or v.web_domain ilike $13 or v.phone_e164 ilike $14)';
      v_needs_view := true;
    else
      v_where := v_where || ' and (v.name ilike $13 or v.web_domain ilike $13)';
    end if;
  end if;

  v_col := case f ->> 'sort'
             when 'score' then 'total'
             when 'company' then 'name'
             when 'grade' then 'grade'
             when 'stage' then 'stage'
             when 'activity' then 'last_activity_at'
             when 'due' then 'due_at'
             else 'created_at'
           end;
  v_dir := case when f ->> 'dir' = 'asc' then 'asc' else 'desc' end;

  -- Lead and business columns only, for picking and counting rows without the contact and signal lookups of
  -- v_leads_caller (one row per lead there too: every lead has its business, and a lead has one score). The
  -- view itself is used only when a filter needs those lookups: signal, mobile, or digits in the search.
  v_source := case when v_needs_view then 'public.v_leads_caller'
                   else '(select l.id, l.segment_id, b.country, b.city, l.grade, l.stage, l.pitch_mode, l.owner_id, '
                     || 'l.due_at, l.created_at, l.last_activity_at, b.name, b.web_domain, sc.total '
                     || 'from public.leads l join public.businesses b on b.id = l.business_id '
                     || 'left join public.scores sc on sc.id = l.score_id)' end;

  -- The page: its ids in order first (every sort column is a lead, business or score column), then the full
  -- rows of those ids only. Under Row Level Security the planner cannot tell how many rows a filter keeps, and
  -- sorting the whole view would look up a contact and a signal for every lead before keeping 50.
  execute format('select array(select v.id from %3$s v where %4$s order by v.%1$I %2$s nulls last, v.id '
                 'limit $15 offset $16)', v_col, v_dir, v_source, v_where)
    into v_ids
    using v_seg, v_country, v_city, v_grade, v_stage, v_pitch, v_signal, v_me, v_owner, v_today, v_from, v_to,
          v_like, v_phone_like, v_size, (v_page - 1) * v_size;

  select coalesce(jsonb_agg(jsonb_build_object(
           'id', v.id, 'business_id', v.business_id, 'name', coalesce(v.name, 'Unnamed business'),
           'segment_id', v.segment_id, 'country', v.country, 'city', v.city, 'website', v.website,
           'web_domain', v.web_domain, 'grade', v.grade, 'total', v.total, 'stage', coalesce(v.stage, 'new'),
           'pitch_mode', v.pitch_mode, 'angle', v.angle, 'test_group', v.test_group,
           'top_signal_type', v.top_signal_type, 'top_signal_quote', v.top_signal_quote,
           'top_signal_url', v.top_signal_url, 'top_signal_at', v.top_signal_at, 'phone_e164', v.phone_e164,
           'phone_type', v.phone_type, 'contact_name', v.contact_name, 'owner_id', v.owner_id,
           'next_step', v.next_step, 'due_at', v.due_at, 'wa_at', v.wa_at,
           'last_activity_at', v.last_activity_at, 'created_at', v.created_at)
           order by array_position(v_ids, v.id)), '[]'::jsonb)
    into v_rows
    from public.v_leads_caller v
   where v.id = any(v_ids);

  -- Money for admins only, through the admin view (empty for everyone else).
  if v_role = 'admin' and cardinality(v_ids) > 0 then
    select coalesce(jsonb_object_agg(m.id::text, m.deal_value_inr), '{}'::jsonb)
      into v_money
      from public.v_leads_admin m
     where m.id = any(v_ids);
    select coalesce(jsonb_agg(e.r || jsonb_build_object('deal_value_inr', v_money -> (e.r ->> 'id')) order by e.n),
                    '[]'::jsonb)
      into v_rows
      from jsonb_array_elements(v_rows) with ordinality as e(r, n);
  end if;

  if v_where = 'true' then
    select count(*) into v_total from public.leads;
  else
    execute 'select count(*) from ' || v_source || ' v where ' || v_where
      into v_total
      using v_seg, v_country, v_city, v_grade, v_stage, v_pitch, v_signal, v_me, v_owner, v_today, v_from, v_to,
            v_like, v_phone_like;
  end if;

  return jsonb_build_object(
    'rows', v_rows,
    'total', v_total,
    'page', v_page,
    'page_size', v_size,
    'filtered', v_where <> 'true',
    'cities', coalesce((
      select jsonb_agg(c.city order by c.city)
      from (select distinct btrim(b.city) as city
              from public.leads l
              join public.businesses b on b.id = l.business_id
             where b.city is not null and btrim(b.city) <> ''
               and (v_country is null or b.country = any(v_country))) c
    ), '[]'::jsonb),
    'views', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', s.id, 'name', s.name, 'shared', s.shared, 'mine', s.user_id = v_me,
               'qs', case when jsonb_typeof(s.query -> 'qs') = 'string' then s.query ->> 'qs' else '' end)
             order by s.name, s.id)
      from public.saved_views s
    ), '[]'::jsonb)
  );
end;
$$;

-- =========================================================================================================
-- Search
-- =========================================================================================================
-- Leads whose business name or website contains q, or is close to it (trigram word similarity, so a typo still
-- finds it), or whose contact has a phone containing its digits (6 or more). Best match first, then newest. Up
-- to max (10 by default, 50 at most). Fewer than 2 characters: none.
--
-- The one security definer here, for speed: under Row Level Security Postgres may not use an index for a
-- condition whose operator is not leakproof (ILIKE and the trigram operators are not), so as the user every
-- search read all businesses. It runs as its owner instead, and checks the role itself first with the same rule
-- as the policies on businesses, leads and contacts (any app role reads every row; anyone else gets nothing).
-- It returns nothing those roles cannot read: no money, no notes, no messages.
create or replace function public.search_leads(q text, max integer default 10)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  v_term text := left(btrim(regexp_replace(coalesce(search_leads.q, ''), '\s+', ' ', 'g')), 80);
  v_limit integer := least(greatest(coalesce(search_leads.max, 10), 1), 50);
  v_like text;
  v_digits text;
begin
  if public.auth_role() not in ('admin', 'caller', 'viewer') or length(v_term) < 2 then
    return '[]'::jsonb;
  end if;
  -- LIKE wildcards in the text are matched literally.
  v_like := '%' || replace(replace(replace(v_term, '\', '\\'), '%', '\%'), '_', '\_') || '%';
  v_digits := regexp_replace(v_term, '\D', '', 'g');
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'id', r.id, 'name', coalesce(r.name, 'Unnamed business'), 'city', r.city, 'country', r.country,
             'web_domain', r.web_domain, 'segment_id', r.segment_id, 'grade', r.grade, 'stage', r.stage,
             'created_at', r.created_at)
           order by r.rank desc, r.created_at desc, r.id)
    from (
      select l.id, b.name, b.city, b.country, b.web_domain, l.segment_id, l.grade, l.stage, l.created_at, m.rank
      from (
        select x.business_id, max(x.rank) as rank
        from (
          -- Contains the text (ranked first), or a word close to it (trigram indexes on name and web_domain).
          select b0.id as business_id,
                 greatest(word_similarity(v_term, b0.name), word_similarity(v_term, coalesce(b0.web_domain, '')))
                   + case when b0.name ilike v_like or b0.web_domain ilike v_like then 1 else 0 end as rank
          from public.businesses b0
          where b0.name ilike v_like or b0.web_domain ilike v_like or v_term <% b0.name or v_term <% b0.web_domain
          union all
          select c.business_id, 3 as rank
          from public.contacts c
          where length(v_digits) >= 6 and c.phone_e164 like '%' || v_digits || '%'
        ) x
        group by x.business_id
      ) m
      join public.leads l on l.business_id = m.business_id
      join public.businesses b on b.id = l.business_id
      order by m.rank desc, l.created_at desc, l.id
      limit v_limit
    ) r
  ), '[]'::jsonb);
end;
$$;

-- =========================================================================================================
-- Insights
-- =========================================================================================================
-- Leads added from from_ts (included) to to_ts (excluded); the page passes India midnights. filters:
-- {"seg": .., "country": .., "group": segment | country | signal | pitch | angle | test_group}.
-- Funnel numbers follow v_funnel: the furthest stage a lead ever reached, from its stage and its stage history
-- (contacted also when it has a first-message date).
--   total, by_segment, by_group   {leads, contacted, replied, meetings, proposals, won}; groups sorted by
--                                 contacted, then leads; an empty key is "unknown", no live signal is "none"
--   quality                       leads, with_phone and own_phone (the best contact's phone, and published on
--                                 their own website), contacted (stage past New), wrong (Wrong contact), the
--                                 median days from the top signal to the lead (India days), votes and up_votes
--   costs                         admins only, else null: spend per India day, the total, the daily cap setting,
--                                 and businesses researched, A and B leads and won leads in the period (the whole
--                                 business, not the segment or country filter, as before)
create or replace function public.insights_summary(from_ts timestamptz, to_ts timestamptz,
                                                   filters jsonb default '{}'::jsonb)
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with p as (
    select nullif(btrim(coalesce(filters, '{}'::jsonb) ->> 'seg'), '') as seg,
           nullif(btrim(coalesce(filters, '{}'::jsonb) ->> 'country'), '') as country,
           coalesce(nullif(btrim(coalesce(filters, '{}'::jsonb) ->> 'group'), ''), 'segment') as grp,
           (select public.auth_role()) as role
  ),
  ranks(stage, rnk) as (
    values ('new', 0), ('contacted', 1), ('talking', 2), ('discovery_booked', 3), ('discovery_done', 3),
           ('proposal_sent', 4), ('won', 5), ('retainer', 5)
  ),
  base as materialized (
    select v.id, v.segment_id, v.country, v.pitch_mode, v.angle, v.test_group, v.stage, v.wa_at, v.top_signal_type,
           v.top_signal_at, v.phone_e164, v.phone_source, v.created_at,
           greatest(coalesce((select r.rnk from ranks r where r.stage = v.stage), 0),
                    coalesce((select max(r.rnk) from public.activities a
                              join ranks r on r.stage = a.payload ->> 'to'
                              where a.lead_id = v.id and a.type = 'stage_change'), 0)) as max_rnk
    from public.v_leads_caller v
    cross join p
    where v.created_at >= from_ts and v.created_at < to_ts
      and (p.seg is null or v.segment_id = p.seg)
      and (p.country is null or v.country = p.country)
  ),
  funnel as (
    select b.id, coalesce(nullif(btrim(b.segment_id), ''), 'unknown') as segment_key,
           coalesce(nullif(btrim(case p.grp
                                   when 'country' then b.country
                                   when 'signal' then coalesce(b.top_signal_type, 'none')
                                   when 'pitch' then b.pitch_mode
                                   when 'angle' then b.angle
                                   when 'test_group' then b.test_group
                                   else b.segment_id
                                 end), ''), 'unknown') as group_key,
           (b.max_rnk >= 1 or b.wa_at is not null) as contacted,
           b.max_rnk >= 2 as replied,
           b.max_rnk >= 3 as meetings,
           b.max_rnk >= 4 as proposals,
           b.max_rnk >= 5 as won
    from base b
    cross join p
  ),
  by_segment as (
    select f.segment_key as id, count(*) as leads, count(*) filter (where f.contacted) as contacted,
           count(*) filter (where f.replied) as replied, count(*) filter (where f.meetings) as meetings,
           count(*) filter (where f.proposals) as proposals, count(*) filter (where f.won) as won
    from funnel f group by f.segment_key
  ),
  by_group as (
    select f.group_key as id, count(*) as leads, count(*) filter (where f.contacted) as contacted,
           count(*) filter (where f.replied) as replied, count(*) filter (where f.meetings) as meetings,
           count(*) filter (where f.proposals) as proposals, count(*) filter (where f.won) as won
    from funnel f group by f.group_key
  ),
  votes as (
    select count(*) as votes, count(*) filter (where fb.rating > 0) as up_votes
    from public.feedback fb
    join public.leads l on l.id = fb.lead_id
    join public.businesses b on b.id = l.business_id
    cross join p
    where l.created_at >= from_ts and l.created_at < to_ts
      and (p.seg is null or l.segment_id = p.seg)
      and (p.country is null or b.country = p.country)
  ),
  spend as (
    select (c.at at time zone 'Asia/Kolkata')::date as day, sum(c.inr) as inr
    from public.costs c
    where (select p.role from p) = 'admin' and c.at >= from_ts and c.at < to_ts
    group by 1
  ),
  days as (
    select d::date as day, round(coalesce(s.inr, 0), 2) as inr
    from generate_series(((from_ts at time zone 'Asia/Kolkata')::date)::timestamp,
                         (least(((to_ts - interval '1 microsecond') at time zone 'Asia/Kolkata')::date,
                                (from_ts at time zone 'Asia/Kolkata')::date + 400))::timestamp,
                         interval '1 day') d
    left join spend s on s.day = d::date
  )
  select jsonb_build_object(
    'total', (
      select jsonb_build_object('leads', count(*), 'contacted', count(*) filter (where f.contacted),
                                'replied', count(*) filter (where f.replied),
                                'meetings', count(*) filter (where f.meetings),
                                'proposals', count(*) filter (where f.proposals),
                                'won', count(*) filter (where f.won))
      from funnel f
    ),
    'by_segment', coalesce((
      select jsonb_agg(to_jsonb(s) order by s.contacted desc, s.leads desc, s.id) from by_segment s
    ), '[]'::jsonb),
    'by_group', coalesce((
      select jsonb_agg(to_jsonb(g) order by g.contacted desc, g.leads desc, g.id) from by_group g
    ), '[]'::jsonb),
    'quality', (
      select jsonb_build_object(
               'leads', count(*),
               'with_phone', count(*) filter (where b.phone_e164 is not null),
               'own_phone', count(*) filter (where b.phone_e164 is not null and b.phone_source = 'website'),
               'contacted', count(*) filter (where b.stage is not null and b.stage <> 'new'),
               'wrong', count(*) filter (where b.stage = 'wrong_contact'),
               'median_signal_age_days',
                 percentile_cont(0.5) within group (
                   order by greatest(0, (b.created_at at time zone 'Asia/Kolkata')::date
                                        - (b.top_signal_at at time zone 'Asia/Kolkata')::date))
                   filter (where b.top_signal_at is not null and b.created_at is not null),
               'votes', (select v.votes from votes v),
               'up_votes', (select v.up_votes from votes v))
      from base b
    ),
    'costs', (
      select case when p.role = 'admin' then jsonb_build_object(
        'days', coalesce((select jsonb_agg(jsonb_build_object('day', d.day, 'inr', d.inr) order by d.day) from days d),
                         '[]'::jsonb),
        'spend', (select coalesce(sum(d.inr), 0) from days d),
        'cap', (select s.value from public.settings s where s.key = 'daily_cap_inr'),
        'researched', (select count(*) from public.businesses b
                       where b.researched_at >= from_ts and b.researched_at < to_ts),
        'good_leads', (select count(*) from public.leads l
                       where l.grade in ('A', 'B') and l.created_at >= from_ts and l.created_at < to_ts),
        'won', (select count(*) from public.leads l
                where l.created_at >= from_ts and l.created_at < to_ts
                  and (l.stage in ('won', 'retainer')
                       or exists (select 1 from public.activities a
                                  where a.lead_id = l.id and a.type = 'stage_change'
                                    and a.payload ->> 'to' in ('won', 'retainer'))))
      ) end
      from p
    )
  )
$$;

-- =========================================================================================================
-- Engine
-- =========================================================================================================
-- Everything live on the Engine page, admin-only under Row Level Security (anyone else gets zeros and empty
-- lists): today's spend (India day), businesses researched and leads added yesterday per segment, source health,
-- the last 20 runs and the last 50 custom searches.
create or replace function public.engine_counts()
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with w as (
    select (((now() at time zone 'Asia/Kolkata')::date - 1)::timestamp at time zone 'Asia/Kolkata') as yesterday,
           (((now() at time zone 'Asia/Kolkata')::date)::timestamp at time zone 'Asia/Kolkata') as today,
           (((now() at time zone 'Asia/Kolkata')::date + 1)::timestamp at time zone 'Asia/Kolkata') as tomorrow
  )
  select jsonb_build_object(
    'spend_today', (select coalesce(sum(c.inr), 0) from public.costs c, w where c.at >= w.today and c.at < w.tomorrow),
    'researched_yesterday', coalesce((
      select jsonb_object_agg(x.segment_id, x.n)
      from (select b.segment_id, count(*) as n from public.businesses b, w
            where b.researched_at >= w.yesterday and b.researched_at < w.today
            group by b.segment_id) x
    ), '{}'::jsonb),
    'leads_yesterday', coalesce((
      select jsonb_object_agg(x.segment_id, x.n)
      from (select l.segment_id, count(*) as n from public.leads l, w
            where l.created_at >= w.yesterday and l.created_at < w.today
            group by l.segment_id) x
    ), '{}'::jsonb),
    'sources', coalesce((
      select jsonb_agg(jsonb_build_object(
               'source', h.source, 'enabled', h.enabled, 'last_ok_at', h.last_ok_at,
               'last_error_at', h.last_error_at, 'last_error', h.last_error, 'blocked_until', h.blocked_until,
               'requests_today', h.requests_today, 'health', h.health)
             order by h.source)
      from public.v_source_health h
    ), '[]'::jsonb),
    'runs', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', r.id, 'kind', r.kind, 'started_at', r.started_at, 'finished_at', r.finished_at,
               'status', r.status, 'stats', r.stats, 'error', r.error)
             order by r.started_at desc, r.id)
      from (select r0.id, r0.kind, r0.started_at, r0.finished_at, r0.status, r0.stats, r0.error
              from public.runs r0 order by r0.started_at desc, r0.id limit 20) r
    ), '[]'::jsonb),
    'queries', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', q.id, 'segment_id', q.segment_id, 'query', q.query, 'status', q.status,
               'created_at', q.created_at)
             order by q.created_at desc, q.id)
      from (select q0.id, q0.segment_id, q0.query, q0.status, q0.created_at
              from public.custom_queries q0 order by q0.created_at desc, q0.id limit 50) q
    ), '[]'::jsonb)
  )
$$;

-- =========================================================================================================
-- Access: signed-in app users (and the service role); never visitors.
-- =========================================================================================================
revoke all on function public.home_summary(integer) from public, anon;
revoke all on function public.nav_counts() from public, anon;
revoke all on function public.lead_detail(uuid, boolean) from public, anon;
revoke all on function public.deals_board(jsonb, integer, integer) from public, anon;
revoke all on function public.leads_page(jsonb, integer, integer) from public, anon;
revoke all on function public.search_leads(text, integer) from public, anon;
revoke all on function public.insights_summary(timestamptz, timestamptz, jsonb) from public, anon;
revoke all on function public.engine_counts() from public, anon;

grant execute on function public.home_summary(integer) to authenticated, service_role;
grant execute on function public.nav_counts() to authenticated, service_role;
grant execute on function public.lead_detail(uuid, boolean) to authenticated, service_role;
grant execute on function public.deals_board(jsonb, integer, integer) to authenticated, service_role;
grant execute on function public.leads_page(jsonb, integer, integer) to authenticated, service_role;
grant execute on function public.search_leads(text, integer) to authenticated, service_role;
grant execute on function public.insights_summary(timestamptz, timestamptz, jsonb) to authenticated, service_role;
grant execute on function public.engine_counts() to authenticated, service_role;

-- PostgREST picks the new functions up at once (Supabase also reloads on DDL by itself).
notify pgrst, 'reload schema';
