-- 0013_scheduler: exact-time scheduling from the database (pg_cron + pg_net).
--
-- Why: on the first night (12 to 13 Nov 2026) GitHub's own scheduler started the 02:00 run at 06:46 IST,
-- dropped the 06:00 run entirely and ran the 10-minute keep-awake ping twice in eight hours. Supabase's
-- pg_cron fires on time, so it now:
--   * pings the web app every 10 minutes (Render's free plan sleeps after 15 idle minutes);
--   * starts the GitHub workflows through the workflow_dispatch API at the planned IST times.
-- The dispatch needs a GitHub token with "Actions: read and write" on this repository, stored in Supabase Vault
-- as `github_dispatch_token` (never in this file). Without it the dispatch jobs log a notice and do nothing.
-- pg_cron runs in UTC: 02:00 IST is 20:30 UTC.
--
-- Local and CI Postgres have no pg_cron or pg_net: everything below is skipped there.

do $outer$
begin
  if not exists (select 1 from pg_available_extensions where name = 'pg_cron')
     or not exists (select 1 from pg_available_extensions where name = 'pg_net') then
    raise notice '0013_scheduler: pg_cron or pg_net not available here, skipped';
    return;
  end if;

  create extension if not exists pg_net with schema extensions;
  create extension if not exists pg_cron;

  execute $fn$
    create or replace function public.dispatch_workflow(workflow text, inputs jsonb default '{}'::jsonb)
    returns bigint
    language plpgsql
    security definer
    set search_path = public, extensions
    as $body$
    declare
      token text;
      request_id bigint;
    begin
      select decrypted_secret into token from vault.decrypted_secrets where name = 'github_dispatch_token' limit 1;
      if token is null or token = '' then
        raise notice 'dispatch_workflow(%): no github_dispatch_token in Vault, nothing started', workflow;
        return null;
      end if;
      select net.http_post(
        url := 'https://api.github.com/repos/with-nument/nument-lead/actions/workflows/' || workflow || '/dispatches',
        body := jsonb_build_object('ref', 'main', 'inputs', inputs),
        headers := jsonb_build_object(
          'Authorization', 'Bearer ' || token,
          'Accept', 'application/vnd.github+json',
          'User-Agent', 'nument-leads-scheduler',
          'Content-Type', 'application/json'
        ),
        timeout_milliseconds := 20000
      ) into request_id;
      return request_id;
    end;
    $body$
  $fn$;
  execute 'revoke all on function public.dispatch_workflow(text, jsonb) from public, anon, authenticated';

  -- Replace earlier versions of these jobs, so re-running the migration is safe.
  perform cron.unschedule(jobname) from cron.job
   where jobname in ('nlead-keep-awake', 'nlead-night', 'nlead-morning', 'nlead-weekly', 'nlead-monthly', 'nlead-backup');

  perform cron.schedule('nlead-keep-awake', '*/10 * * * *',
    $job$select net.http_get('https://nument-leads-web.onrender.com/api/health', timeout_milliseconds := 60000)$job$);
  perform cron.schedule('nlead-night',   '30 20 * * *', $job$select public.dispatch_workflow('night.yml')$job$);     -- 02:00 IST
  perform cron.schedule('nlead-morning', '30 0 * * *',  $job$select public.dispatch_workflow('morning.yml')$job$);   -- 06:00 IST
  perform cron.schedule('nlead-weekly',  '30 1 * * 1',  $job$select public.dispatch_workflow('weekly.yml')$job$);    -- Mon 07:00 IST
  perform cron.schedule('nlead-monthly', '0 17 1 * *',  $job$select public.dispatch_workflow('monthly.yml')$job$);   -- 1st, 22:30 IST
  perform cron.schedule('nlead-backup',  '30 17 * * 0', $job$select public.dispatch_workflow('backup.yml')$job$);    -- Sun 23:00 IST
end
$outer$;
