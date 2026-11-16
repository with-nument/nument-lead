-- 0033_inbox_calls.sql : the email side of the app: Inbox, Calls and a lead's conversation (16 Nov 2026, lane W3)
--
-- The engine (0021, 0022) sends the sequence, reads the replies and drafts answers; until now the app could not
-- show any of it. Like 0024, each screen makes one call to one function that returns one jsonb value and runs as
-- the signed-in user (security invoker), so Row Level Security decides every row: email threads and messages,
-- plan pages and proposals are for admins and callers only (a viewer gets empty lists), offers and startup
-- profiles for every app role.
--
--   inbox_page(tab, cursor_at, cursor_id, page_size)  one page of the Inbox and the count of every tab:
--       replies   the latest answer from a person on each conversation that nobody has dealt with yet (no
--                 outgoing message approved, queued, sent or cancelled after it), with the drafted reply
--       review    the sequence emails (day 0, 3, 7, 12) waiting in 'review' for a person
--       done      outgoing emails on their way or gone (approved, queued, sending, sent, failed) and the ones a
--                 person cancelled (the engine's own cancellations carry an error and are left out), newest first
--   calls_page()                 every lead with a meeting: today, coming up and the last 30 days (India time),
--                                with the booking, the pre-call brief, the offer, plan page views and the proposal
--   lead_conversation(lead_id)   one lead's emails, offers, plan pages, startup profile, briefs and proposals
--   review_message(message_id, action, subject, body)   approve, cancel, reopen or edit an outgoing message
--   save_call_notes(lead_id, notes)   the founder's call notes into a draft proposal for the engine to write
--
-- review_message changes only what the 0022 policy email_messages_review allows: subject, body and status of an
-- outgoing message that has not gone out ('draft', 'review', 'approved' to 'draft', 'review', 'approved' or
-- 'cancelled'). It never sets 'queued', 'sending' or 'sent': an approved message is sent by the engine's outreach
-- run, which checks every gate again before it sends.
--
-- save_call_notes needs a new insert path on proposals (0021 gave people select and update only): a person may
-- insert a draft with empty content and their notes, nothing else (policy and column grant below). The engine's
-- proposals phase then fills `content` (outreach/proposals.py).

-- =========================================================================================================
-- Inbox
-- =========================================================================================================
-- Each item: {key, tab, at, lead_id, thread_id, company, city, country, grade, stage, contact_name, contact_role,
--   to_email, inbound {id, subject, body, at, classification, confidence, suggested_reply} | null,
--   draft {id, step, subject, body, status, scheduled_for, sent_at, updated_at, error} | null,
--   last_out {id, step, subject, body, at} | null}
-- replies: inbound is the answer, draft the reply waiting for a person (if the engine wrote one), last_out our
--   last email before the answer. review: draft is the email to approve, inbound null. done: draft is the email
--   that was dealt with, inbound the answer it replied to (step null) or null.
-- The cursor is the last item's (at, key); pages come newest first. Classifications 'unsubscribe' and
-- 'out_of_office' are handled by the engine on its own and never wait in Replies.

-- One Inbox item (defined first, inbox_page calls it). Internal, runs as the same user.
create or replace function public._inbox_item(tab text, message_id uuid, thread_id uuid, at timestamptz)
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with t as (
    select t0.id, t0.lead_id, t0.contact_id, t0.to_email, t0.status as thread_status
      from public.email_threads t0 where t0.id = _inbox_item.thread_id
  ),
  me as (
    select m.* from public.email_messages m where m.id = _inbox_item.message_id
  ),
  -- replies: the answer is `me`; done (step null): the latest answer before it
  inbound as (
    select m.* from public.email_messages m
     where _inbox_item.tab = 'replies' and m.id = _inbox_item.message_id
    union all
    select m.* from (
      select m1.* from public.email_messages m1, me
       where _inbox_item.tab = 'done' and me.step is null and m1.thread_id = me.thread_id and m1.direction = 'in'
         and coalesce(m1.sent_at, m1.created_at) <= coalesce(me.sent_at, me.updated_at)
       order by coalesce(m1.sent_at, m1.created_at) desc, m1.id desc
       limit 1) m
  ),
  draft as (
    select m.* from public.email_messages m
     where _inbox_item.tab in ('review', 'done') and m.id = _inbox_item.message_id
    union all
    select m.* from (
      select m1.* from public.email_messages m1
       where _inbox_item.tab = 'replies' and m1.thread_id = _inbox_item.thread_id and m1.direction = 'out'
         and m1.step is null and m1.status in ('draft', 'review')
       order by m1.created_at desc, m1.id desc
       limit 1) m
  ),
  last_out as (
    select m1.* from public.email_messages m1
     where m1.thread_id = _inbox_item.thread_id and m1.direction = 'out' and m1.status = 'sent'
       and (_inbox_item.tab <> 'replies' or m1.sent_at <= _inbox_item.at)
       and m1.id <> _inbox_item.message_id
     order by m1.sent_at desc, m1.id desc
     limit 1
  )
  select jsonb_build_object(
    'key', _inbox_item.message_id,
    'tab', _inbox_item.tab,
    'at', _inbox_item.at,
    'thread_id', t.id,
    'thread_status', t.thread_status,
    'lead_id', t.lead_id,
    'company', b.name,
    'city', b.city,
    'country', b.country,
    'grade', l.grade,
    'stage', l.stage,
    'contact_name', c.name,
    'contact_role', c.role,
    'to_email', t.to_email,
    'inbound', (select jsonb_build_object(
                  'id', i.id, 'subject', i.subject, 'body', i.body, 'at', coalesce(i.sent_at, i.created_at),
                  'classification', i.classification, 'confidence', i.classification_confidence,
                  'suggested_reply', i.suggested_reply)
                from inbound i limit 1),
    'draft', (select jsonb_build_object(
                'id', d.id, 'step', d.step, 'subject', d.subject, 'body', d.body, 'status', d.status,
                'scheduled_for', d.scheduled_for, 'sent_at', d.sent_at, 'updated_at', d.updated_at, 'error', d.error)
              from draft d limit 1),
    'last_out', (select jsonb_build_object('id', o.id, 'step', o.step, 'subject', o.subject, 'body', o.body,
                                           'at', o.sent_at)
                 from last_out o)
  )
  from t
  left join public.leads l on l.id = t.lead_id
  left join public.businesses b on b.id = l.business_id
  left join public.contacts c on c.id = t.contact_id
$$;

create or replace function public.inbox_page(
  tab text default 'replies',
  cursor_at timestamptz default null,
  cursor_id uuid default null,
  page_size integer default 50
)
returns jsonb
language plpgsql
stable
set search_path = public, extensions
as $$
declare
  v_tab text := lower(coalesce(inbox_page.tab, 'replies'));
  v_size integer := least(greatest(coalesce(inbox_page.page_size, 50), 1), 200);
  v_items jsonb;
  v_counts jsonb;
begin
  if v_tab not in ('replies', 'review', 'done') then
    raise exception 'inbox_page: unknown tab %', inbox_page.tab using errcode = '22023';
  end if;

  with
  -- The latest inbound message of each thread that still waits for a person.
  replies as materialized (
    select distinct on (m.thread_id) m.id, m.thread_id, coalesce(m.sent_at, m.created_at) as at
      from public.email_messages m
     where m.direction = 'in' and m.status = 'received'
       and coalesce(m.classification, '') not in ('unsubscribe', 'out_of_office')
     order by m.thread_id, coalesce(m.sent_at, m.created_at) desc, m.id desc
  ),
  open_replies as materialized (
    select r.* from replies r
     where not exists (
       select 1 from public.email_messages o
        where o.thread_id = r.thread_id and o.direction = 'out'
          and (o.status in ('approved', 'queued', 'sending', 'sent')
               or (o.step is null and o.status in ('cancelled', 'failed')))
          and coalesce(o.sent_at, o.updated_at) >= r.at)
  ),
  review as materialized (
    select m.id, m.thread_id, m.created_at as at
      from public.email_messages m
     where m.direction = 'out' and m.step is not null and m.status = 'review'
  ),
  done as materialized (
    select m.id, m.thread_id, coalesce(m.sent_at, m.updated_at) as at
      from public.email_messages m
     where m.direction = 'out'
       and (m.status in ('approved', 'queued', 'sending', 'sent', 'failed')
            or (m.status = 'cancelled' and m.error is null))
  )
  select jsonb_build_object(
           'replies', (select count(*) from open_replies),
           'review', (select count(*) from review),
           'done', (select count(*) from done)),
         coalesce((
           select jsonb_agg(public._inbox_item(v_tab, x.id, x.thread_id, x.at) order by x.at desc, x.id desc)
             from (
               select s.id, s.thread_id, s.at
                 from (select * from open_replies where v_tab = 'replies'
                       union all select * from review where v_tab = 'review'
                       union all select * from done where v_tab = 'done') s
                where inbox_page.cursor_at is null
                   or (s.at, s.id) < (inbox_page.cursor_at, coalesce(inbox_page.cursor_id, 'ffffffff-ffff-ffff-ffff-ffffffffffff'::uuid))
                order by s.at desc, s.id desc
                limit v_size + 1
             ) x
         ), '[]'::jsonb)
    into v_counts, v_items;

  return jsonb_build_object(
    'tab', v_tab,
    'counts', v_counts,
    'items', case when jsonb_array_length(v_items) > v_size then v_items - v_size else v_items end,
    'next_cursor', case when jsonb_array_length(v_items) > v_size then
      jsonb_build_object('at', v_items -> (v_size - 1) ->> 'at', 'id', v_items -> (v_size - 1) ->> 'key') end
  );
end;
$$;


-- =========================================================================================================
-- Calls
-- =========================================================================================================
-- today      meetings on today's date in India, earliest first
-- upcoming   later meetings, earliest first (up to 100)
-- earlier    meetings in the 30 days before today, latest first (up to 100)
-- Each call: {lead_id, meeting_at, company, website, city, country, grade, stage, contact_name, contact_role,
--   email, booking (the latest 'booking' activity payload) | null, brief {at, meeting_at, content} | null (the
--   latest 'brief'), offer {key, name, promise, timeline, typical_range,
--   why_now} | null, plan {views, first_viewed_at, last_viewed_at} | null, proposal {id, status, call_notes,
--   drafted, updated_at} | null (the latest)}

-- One call (defined first, calls_page calls it). Internal, runs as the same user.
create or replace function public._call_item(lead_id uuid)
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  select jsonb_build_object(
    'lead_id', l.id,
    'meeting_at', l.meeting_at,
    'company', b.name,
    'website', b.website,
    'city', b.city,
    'country', b.country,
    'grade', l.grade,
    'stage', l.stage,
    'contact_name', pc.name,
    'contact_role', pc.role,
    'email', pc.email,
    'booking', (select a.payload from public.activities a
                 where a.lead_id = l.id and a.type = 'booking' order by a.at desc, a.id desc limit 1),
    'brief', (select jsonb_build_object('at', a.at, 'meeting_at', a.payload ->> 'meeting_at',
                                        'content', a.payload -> 'content')
                from public.activities a
               where a.lead_id = l.id and a.type = 'brief'
               order by a.at desc, a.id desc
               limit 1),
    'offer', (select jsonb_build_object('key', o.key, 'name', o.name, 'promise', o.promise, 'timeline', o.timeline,
                                        'typical_range', o.typical_range, 'why_now', lo.why_now)
                from public.lead_offers lo join public.offers o on o.key = lo.offer_key
               where lo.lead_id = l.id and lo.rank = 1),
    'plan', (select jsonb_build_object('views', coalesce(sum(pp.views), 0), 'first_viewed_at', min(pp.first_viewed_at),
                                       'last_viewed_at', max(pp.last_viewed_at))
               from public.plan_pages pp where pp.lead_id = l.id
              having count(*) > 0),
    'proposal', (select jsonb_build_object('id', pr.id, 'status', pr.status, 'call_notes', pr.call_notes,
                                           'drafted', pr.content <> '{}'::jsonb, 'updated_at', pr.updated_at)
                   from public.proposals pr where pr.lead_id = l.id
                  order by pr.created_at desc, pr.id desc limit 1)
  )
  from public.leads l
  join public.businesses b on b.id = l.business_id
  left join public.v_primary_contact pc on pc.business_id = l.business_id
  where l.id = _call_item.lead_id
$$;

create or replace function public.calls_page()
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with p as (
    select (now() at time zone 'Asia/Kolkata')::date as today
  ),
  calls as materialized (
    select l.id, l.meeting_at, (l.meeting_at at time zone 'Asia/Kolkata')::date as day
      from public.leads l, p
     where l.meeting_at is not null
       and (l.meeting_at at time zone 'Asia/Kolkata')::date >= p.today - 30
  ),
  all_calls as (
    select c.day, c.meeting_at, c.id, public._call_item(c.id) as item from calls c
  )
  select jsonb_build_object(
    'today', coalesce((select jsonb_agg(r.item order by r.meeting_at, r.id) from all_calls r, p where r.day = p.today), '[]'::jsonb),
    'upcoming', coalesce((select jsonb_agg(x.item order by x.meeting_at, x.id) from (
        select r.* from all_calls r, p where r.day > p.today order by r.meeting_at, r.id limit 100) x), '[]'::jsonb),
    'earlier', coalesce((select jsonb_agg(x.item order by x.meeting_at desc, x.id) from (
        select r.* from all_calls r, p where r.day < p.today order by r.meeting_at desc, r.id limit 100) x), '[]'::jsonb)
  )
$$;


-- =========================================================================================================
-- A lead's conversation
-- =========================================================================================================
-- null when the lead does not exist or is not visible. Otherwise:
--   lead_id, meeting_at
--   thread     the open thread, else the latest one: {id, status, stop_reason, mode, to_email, paused_until,
--              created_at} | null; threads: how many there are
--   messages   every message of every thread of the lead, oldest first (up to 200)
--   offers     rank 1 and 2 with the offer's name, promise, timeline and typical range
--   plan_pages {token, kind, status, views, first_viewed_at, last_viewed_at, created_at, expires_at}, newest first
--   startup_profile   every startup_profiles column (with evidence) | null
--   briefs     the 'brief' activities {at, meeting_at, content}, newest first (up to 10)
--   bookings   the 'booking' activity payloads, newest first (up to 10)
--   proposals  {id, status, call_notes, content, plan_token, created_at, updated_at}, newest first
create or replace function public.lead_conversation(lead_id uuid)
returns jsonb
language plpgsql
stable
set search_path = public, extensions
as $$
declare
  v_business uuid;
  v_meeting timestamptz;
begin
  select l.business_id, l.meeting_at into v_business, v_meeting
    from public.leads l where l.id = lead_conversation.lead_id;
  if v_business is null then
    return null;
  end if;
  return jsonb_build_object(
    'lead_id', lead_conversation.lead_id,
    'meeting_at', v_meeting,
    'thread', (
      select jsonb_build_object('id', t.id, 'status', t.status, 'stop_reason', t.stop_reason, 'mode', t.mode,
                                'to_email', t.to_email, 'paused_until', t.paused_until, 'created_at', t.created_at)
        from public.email_threads t
       where t.lead_id = lead_conversation.lead_id
       order by (t.status = 'open') desc, t.created_at desc, t.id desc
       limit 1),
    'threads', (select count(*) from public.email_threads t where t.lead_id = lead_conversation.lead_id),
    'messages', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', m.id, 'thread_id', m.thread_id, 'direction', m.direction, 'step', m.step, 'subject', m.subject,
               'body', m.body, 'status', m.status, 'scheduled_for', m.scheduled_for, 'sent_at', m.sent_at,
               'classification', m.classification, 'confidence', m.classification_confidence,
               'suggested_reply', m.suggested_reply, 'error', m.error, 'created_at', m.created_at,
               'updated_at', m.updated_at)
             order by coalesce(m.sent_at, m.scheduled_for, m.created_at), m.created_at, m.id)
        from (select m0.* from public.email_messages m0
                join public.email_threads t on t.id = m0.thread_id
               where t.lead_id = lead_conversation.lead_id
               order by coalesce(m0.sent_at, m0.scheduled_for, m0.created_at) desc, m0.id desc
               limit 200) m
    ), '[]'::jsonb),
    'offers', coalesce((
      select jsonb_agg(jsonb_build_object('rank', lo.rank, 'key', o.key, 'name', o.name, 'promise', o.promise,
                                          'timeline', o.timeline, 'typical_range', o.typical_range,
                                          'why_now', lo.why_now, 'cited_ids', lo.cited_ids)
             order by lo.rank)
        from public.lead_offers lo join public.offers o on o.key = lo.offer_key
       where lo.lead_id = lead_conversation.lead_id
    ), '[]'::jsonb),
    'plan_pages', coalesce((
      select jsonb_agg(jsonb_build_object('token', pp.token, 'kind', pp.kind, 'status', pp.status, 'views', pp.views,
                                          'first_viewed_at', pp.first_viewed_at, 'last_viewed_at', pp.last_viewed_at,
                                          'created_at', pp.created_at, 'expires_at', pp.expires_at)
             order by pp.created_at desc, pp.token)
        from public.plan_pages pp where pp.lead_id = lead_conversation.lead_id
    ), '[]'::jsonb),
    'startup_profile', (select to_jsonb(sp) from public.startup_profiles sp where sp.business_id = v_business),
    'briefs', coalesce((
      select jsonb_agg(jsonb_build_object('at', a.at, 'meeting_at', a.payload ->> 'meeting_at',
                                          'content', a.payload -> 'content') order by a.at desc, a.id)
        from (select a0.* from public.activities a0
               where a0.lead_id = lead_conversation.lead_id and a0.type = 'brief'
               order by a0.at desc, a0.id limit 10) a
    ), '[]'::jsonb),
    'bookings', coalesce((
      select jsonb_agg(a.payload || jsonb_build_object('at', a.at) order by a.at desc, a.id)
        from (select a0.* from public.activities a0
               where a0.lead_id = lead_conversation.lead_id and a0.type = 'booking'
               order by a0.at desc, a0.id limit 10) a
    ), '[]'::jsonb),
    'proposals', coalesce((
      select jsonb_agg(jsonb_build_object('id', pr.id, 'status', pr.status, 'call_notes', pr.call_notes,
                                          'content', pr.content, 'plan_token', pr.plan_token,
                                          'created_at', pr.created_at, 'updated_at', pr.updated_at)
             order by pr.created_at desc, pr.id)
        from public.proposals pr where pr.lead_id = lead_conversation.lead_id
    ), '[]'::jsonb)
  );
end;
$$;

-- =========================================================================================================
-- Reviewing an outgoing message
-- =========================================================================================================
-- action   from                        to          also
-- approve  draft, review               approved    subject and body when given (an edit and approve in one)
-- cancel   draft, review, approved     cancelled
-- reopen   approved                    review      (undo an approval before the engine picks it up)
-- edit     draft, review, approved     unchanged   subject and/or body (a null keeps the current text)
-- Returns {id, status, subject, body, updated_at}. Raises 'P0002' when the message is not an outgoing message this
-- user may change in that state (already sent, being sent, received, or not visible).
create or replace function public.review_message(
  message_id uuid,
  action text,
  subject text default null,
  body text default null
)
returns jsonb
language plpgsql
volatile
set search_path = public, extensions
as $$
declare
  v_action text := lower(coalesce(review_message.action, ''));
  v_from text[];
  v_row jsonb;
begin
  v_from := case v_action
    when 'approve' then array['draft', 'review']
    when 'cancel' then array['draft', 'review', 'approved']
    when 'reopen' then array['approved']
    when 'edit' then array['draft', 'review', 'approved']
  end;
  if v_from is null then
    raise exception 'review_message: unknown action %', review_message.action using errcode = '22023';
  end if;
  if v_action in ('approve', 'edit') and review_message.body is not null and btrim(review_message.body) = '' then
    raise exception 'review_message: the body is empty' using errcode = '22023';
  end if;

  update public.email_messages m
     set status = case v_action when 'approve' then 'approved' when 'cancel' then 'cancelled'
                                when 'reopen' then 'review' else m.status end,
         subject = case when v_action in ('approve', 'edit') and review_message.subject is not null
                        then nullif(btrim(review_message.subject), '') else m.subject end,
         body = case when v_action in ('approve', 'edit') and review_message.body is not null
                     then review_message.body else m.body end,
         updated_at = now()
   where m.id = review_message.message_id and m.direction = 'out' and m.status = any(v_from)
  returning jsonb_build_object('id', m.id, 'status', m.status, 'subject', m.subject, 'body', m.body,
                               'updated_at', m.updated_at)
    into v_row;
  if v_row is null then
    raise exception 'review_message: this email can no longer be changed' using errcode = 'P0002';
  end if;
  return v_row;
end;
$$;

-- =========================================================================================================
-- Call notes into a draft proposal
-- =========================================================================================================
-- Saves the notes on the lead's latest proposal that is still a draft; with none, starts one (status 'draft',
-- empty content), which the engine's proposals phase then writes. A draft the engine already wrote keeps its
-- content (only the notes change). Returns {id, created, drafted}.
create policy proposals_insert on public.proposals for insert to authenticated
  with check (public.auth_role() in ('admin', 'caller') and status = 'draft' and content = '{}'::jsonb);
grant insert (lead_id, call_notes) on public.proposals to authenticated;

create or replace function public.save_call_notes(lead_id uuid, notes text)
returns jsonb
language plpgsql
volatile
set search_path = public, extensions
as $$
declare
  v_id uuid;
  v_drafted boolean;
  v_notes text := btrim(coalesce(save_call_notes.notes, ''));
begin
  if v_notes = '' then
    raise exception 'save_call_notes: the notes are empty' using errcode = '22023';
  end if;
  if not exists (select 1 from public.leads l where l.id = save_call_notes.lead_id) then
    raise exception 'save_call_notes: lead not found' using errcode = 'P0002';
  end if;
  update public.proposals pr
     set call_notes = v_notes, updated_at = now()
   where pr.id = (select p2.id from public.proposals p2
                   where p2.lead_id = save_call_notes.lead_id and p2.status = 'draft'
                   order by p2.created_at desc, p2.id desc limit 1)
  returning pr.id, pr.content <> '{}'::jsonb into v_id, v_drafted;
  if v_id is not null then
    return jsonb_build_object('id', v_id, 'created', false, 'drafted', v_drafted);
  end if;
  insert into public.proposals (lead_id, call_notes) values (save_call_notes.lead_id, v_notes)
  returning id into v_id;
  return jsonb_build_object('id', v_id, 'created', true, 'drafted', false);
end;
$$;

-- =========================================================================================================
revoke all on function public.inbox_page(text, timestamptz, uuid, integer) from public, anon;
revoke all on function public._inbox_item(text, uuid, uuid, timestamptz) from public, anon;
revoke all on function public.calls_page() from public, anon;
revoke all on function public._call_item(uuid) from public, anon;
revoke all on function public.lead_conversation(uuid) from public, anon;
revoke all on function public.review_message(uuid, text, text, text) from public, anon;
revoke all on function public.save_call_notes(uuid, text) from public, anon;

grant execute on function public.inbox_page(text, timestamptz, uuid, integer) to authenticated;
grant execute on function public._inbox_item(text, uuid, uuid, timestamptz) to authenticated;
grant execute on function public.calls_page() to authenticated;
grant execute on function public._call_item(uuid) to authenticated;
grant execute on function public.lead_conversation(uuid) to authenticated;
grant execute on function public.review_message(uuid, text, text, text) to authenticated;
grant execute on function public.save_call_notes(uuid, text) to authenticated;

notify pgrst, 'reload schema';
