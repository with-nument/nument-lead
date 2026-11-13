-- 0017_midday_run.sql : a 13:00 IST midday run and its hot-lead email (founder, 13 Nov 2026)
--
-- A builder job post or a public ask is worth most on the day it appears. The midday run reads the day's new
-- signals (job feeds, grounded searches, careers pages), collects any late AI batch, then verifies, scores,
-- judges and writes messages, and emails the A and B leads made since the morning email (only when there is
-- at least one). pg_cron starts it like the other runs (0013); local and CI Postgres skip that part.

alter table public.runs drop constraint if exists runs_kind_check;
alter table public.runs add constraint runs_kind_check
  check (kind in ('night','morning','midday','sheet_sync','weekly','monthly','manual'));

do $outer$
begin
  if not exists (select 1 from pg_extension where extname = 'pg_cron') then
    raise notice '0017_midday_run: pg_cron not installed here, schedule skipped';
    return;
  end if;
  perform cron.unschedule(jobname) from cron.job where jobname = 'nlead-midday';
  perform cron.schedule('nlead-midday', '30 7 * * *', $job$select public.dispatch_workflow('midday.yml')$job$);  -- 13:00 IST
end
$outer$;
