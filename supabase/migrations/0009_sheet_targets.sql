-- 0009_sheet_targets.sql : separate snapshots for the staging sheet, and the Step 13 sheet settings
--
-- One Supabase project serves dev and prod for now (A.13.4). Dev writes the staging spreadsheet and prod
-- writes the live sheets, so each needs its own snapshots and its own sheet_state entry. If they shared the
-- keys 'master' and 'caller', a staging push would replace the live snapshot and the next live pull would
-- read stale cells as edits (the 12 Nov 2026 bug, D-045). Staging uses 'staging_master' and 'staging_caller'.

alter table public.sheet_snapshots drop constraint if exists sheet_snapshots_sheet_check;
alter table public.sheet_snapshots add constraint sheet_snapshots_sheet_check
  check (sheet in ('master','caller','staging_master','staging_caller'));

-- Step 13 settings (A.13.4). Only missing keys are added, so values changed in the app are kept.
insert into public.settings (key, value) values
  ('send_per_day',          '50'::jsonb),   -- brand-new leads shown in Today each day (13.5.4)
  ('today_rows_max',        '60'::jsonb),   -- most rows in the Today list (13.6.4)
  ('weekly_contact_target', '150'::jsonb)   -- the "Contacted this week" tile target (13.6.4)
on conflict (key) do nothing;

update public.settings
   set value = value || '{"staging_master": {"state": "ok"}, "staging_caller": {"state": "ok"}}'::jsonb
 where key = 'sheet_state'
   and not (value ? 'staging_master');
