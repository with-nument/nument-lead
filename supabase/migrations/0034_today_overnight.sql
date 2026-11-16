-- 0034_today_overnight.sql : the numbers on Today's "Overnight" card (16 Nov 2026, lane W5)
--
-- One call, one jsonb value, run as the signed-in user (security invoker) like 0024 and 0033, so Row Level
-- Security decides every count: email and plan page numbers are for admins and callers only (a viewer gets 0).
-- The window starts at 6 pm India time yesterday, so a morning look covers the night's engine run and the
-- emails that went out and came back since the evening.
--
--   since                  the start of the window (6 pm yesterday, India time)
--   startups_found         businesses the engine added in the window
--   startups_qualified     leads created in the window (a lead exists only once a business passed every check)
--   emails_sent            outgoing emails sent in the window
--   replies                emails received in the window
--   plan_pages_viewed      plan pages (and proposal pages) viewed in the window
--   bounced                'email_bounced' activities in the window
--
-- Email opens are not tracked and not counted anywhere.
create or replace function public.today_overnight()
returns jsonb
language sql
stable
set search_path = public, extensions
as $$
  with w as (
    select ((((now() at time zone 'Asia/Kolkata')::date - 1)::timestamp + interval '18 hours') at time zone 'Asia/Kolkata') as since
  )
  select jsonb_build_object(
    'since', w.since,
    'startups_found', (select count(*) from public.businesses b where b.created_at >= w.since),
    'startups_qualified', (select count(*) from public.leads l where l.created_at >= w.since),
    'emails_sent', (select count(*) from public.email_messages m
                     where m.direction = 'out' and m.status = 'sent' and m.sent_at >= w.since),
    'replies', (select count(*) from public.email_messages m where m.direction = 'in' and m.created_at >= w.since),
    'plan_pages_viewed', (select count(*) from public.plan_pages pp where pp.last_viewed_at >= w.since),
    'bounced', (select count(*) from public.activities a where a.type = 'email_bounced' and a.at >= w.since)
  )
  from w;
$$;

revoke all on function public.today_overnight() from public, anon;
grant execute on function public.today_overnight() to authenticated;

notify pgrst, 'reload schema';
