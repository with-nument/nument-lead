-- rls_test.sql : run against DEV only (never prod). Everything is rolled back at the end.
-- Locally it also runs against a throwaway Postgres: cd engine && uv run pytest tests/test_rls.py
-- psql "$DATABASE_URL_DEV" -v ON_ERROR_STOP=1 -v admin=<uuid> -v caller=<uuid> -v viewer=<uuid> -f supabase/tests/rls_test.sql
begin;

-- Fixture (as the engine) -------------------------------------------------------
insert into public.businesses (id, segment_id, name, norm_name, country, city, status)
values ('00000000-0000-4000-8000-000000000001', 'clinics-in', 'Test Skin Clinic',
        'test skin clinic', 'in', 'Pune', 'qualified');
insert into public.leads (id, business_id, segment_id, grade, pitch_mode, deal_value_inr)
values ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001',
        'clinics-in', 'A', 'fit_only', 50000);

-- Triggers ------------------------------------------------------------------------
update public.leads set stage = 'contacted' where id = '00000000-0000-4000-8000-000000000002';
do $$
begin
  if (select wa_at from public.leads where id = '00000000-0000-4000-8000-000000000002') is null then
    raise exception 'FAIL: contacted without a date did not fill wa_at';
  end if;
  if (select count(*) from public.activities
      where lead_id = '00000000-0000-4000-8000-000000000002'
        and type in ('lead_created','stage_change')) <> 2 then
    raise exception 'FAIL: triggers did not log lead_created and stage_change';
  end if;
  begin
    insert into public.leads (business_id, segment_id, grade, pitch_mode)
    values ('00000000-0000-4000-8000-000000000001', 'clinics-in', 'B', 'fit_only');
    raise exception 'FAIL: a second open lead for one business was allowed';
  exception when unique_violation then null;   -- expected
  end;
end $$;

-- Anonymous visitors get nothing ----------------------------------------------------
set local role anon;
do $$
begin
  perform 1 from public.v_today limit 1;
  raise exception 'FAIL: anon can read v_today';
exception when insufficient_privilege then null;   -- expected
end $$;

-- Caller: no money, no costs, can read leads -----------------------------------------
set local role authenticated;
select set_config('request.jwt.claims', json_build_object('sub', :'caller', 'role', 'authenticated')::text, true);
do $$
begin
  begin
    perform deal_value_inr from public.leads limit 1;
    raise exception 'FAIL: caller can read leads.deal_value_inr';
  exception when insufficient_privilege then null;
  end;
  begin
    perform 1 from public.v_pipeline limit 1;
    raise exception 'FAIL: caller can read v_pipeline';
  exception when insufficient_privilege then null;
  end;
  if exists (select 1 from public.v_leads_admin) then
    raise exception 'FAIL: caller got rows from v_leads_admin';
  end if;
  if exists (select 1 from public.costs) then
    raise exception 'FAIL: caller can read costs';
  end if;
  if not exists (select 1 from public.v_leads_caller where id = '00000000-0000-4000-8000-000000000002') then
    raise exception 'FAIL: caller cannot read leads';
  end if;
end $$;

-- Viewer: cannot edit a lead --------------------------------------------------------
select set_config('request.jwt.claims', json_build_object('sub', :'viewer', 'role', 'authenticated')::text, true);
do $$
declare n int;
begin
  update public.leads set notes = 'x' where id = '00000000-0000-4000-8000-000000000002';
  get diagnostics n = row_count;
  if n > 0 then raise exception 'FAIL: viewer updated a lead'; end if;
end $$;

-- Admin: sees money through v_leads_admin ----------------------------------------------
select set_config('request.jwt.claims', json_build_object('sub', :'admin', 'role', 'authenticated')::text, true);
do $$
begin
  if (select deal_value_inr from public.v_leads_admin
      where id = '00000000-0000-4000-8000-000000000002') is distinct from 50000 then
    raise exception 'FAIL: admin cannot read money through v_leads_admin';
  end if;
end $$;

rollback;
