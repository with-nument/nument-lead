-- 0003_rls.sql : Row Level Security, grants and storage

-- 1. RLS on every table -------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'settings','segments','businesses','source_records','signals','pages','facts','contacts',
    'scores','profiles','leads','activities','feedback','suppression','runs','costs',
    'llm_batches','llm_batch_reservations','llm_cache','source_health','sheet_snapshots',
    'golden_labels','custom_queries','inbox_posts','saved_views']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- 2. Nothing for anonymous visitors; nothing new for anyone by default ---------
revoke all on all tables    in schema public from anon;
revoke all on all sequences in schema public from anon;
alter default privileges for role postgres in schema public revoke all on tables    from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;

-- 3. Policies -------------------------------------------------------------------
-- profiles: own row; admins see all. Roles change only through the admin client (Step 15).
create policy profiles_select on public.profiles for select to authenticated
  using (user_id = auth.uid() or public.auth_role() = 'admin');
create policy profiles_update_self on public.profiles for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
revoke insert, update, delete on public.profiles from authenticated;
grant update (full_name) on public.profiles to authenticated;

-- settings and segments
create policy settings_admin_select on public.settings for select to authenticated
  using (public.auth_role() = 'admin');
create policy settings_admin_update on public.settings for update to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy segments_read on public.segments for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy segments_admin_update on public.segments for update to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

-- research tables: read for every app role
create policy businesses_read on public.businesses for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy contacts_read on public.contacts for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy signals_read on public.signals for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy facts_read on public.facts for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy scores_read on public.scores for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy source_records_admin on public.source_records for select to authenticated
  using (public.auth_role() = 'admin');

-- pages: titles and links for everyone in the app; the raw text stays with the engine
create policy pages_read on public.pages for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
revoke select on public.pages from authenticated;
grant select (id, business_id, url, fetched_at, http_status, render_mode, title, robots_allowed)
  on public.pages to authenticated;

-- contacts: Wrong contact and Do not contact set one flag (Step 15)
create policy contacts_flag on public.contacts for update to authenticated
  using (public.auth_role() in ('admin','caller'))
  with check (public.auth_role() in ('admin','caller'));
revoke update on public.contacts from authenticated;
grant update (do_not_contact, updated_at) on public.contacts to authenticated;

-- signals: ads_running is entered by hand on the lead page (Step 7.5.6)
create policy signals_manual_ads on public.signals for insert to authenticated
  with check (public.auth_role() in ('admin','caller') and type = 'ads_running' and source = 'manual');

-- leads: rows readable by app roles, editable by admin and caller; money hidden by column grants
create policy leads_read on public.leads for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy leads_edit on public.leads for update to authenticated
  using (public.auth_role() in ('admin','caller'))
  with check (public.auth_role() in ('admin','caller'));
revoke select, insert, update, delete on public.leads from authenticated;
grant select (id, business_id, segment_id, score_id, grade, pitch_mode, test_group, angle, channel,
              message, message_alt, email_subject, email_body, followup_d3, followup_d7,
              message_model, message_check_score, stage, owner_id, wa_at, call_at, d3_at, d7_at,
              meeting_at, next_step, due_at, skipped_until, regen_requested_at, notes,
              created_at, updated_at, last_activity_at)
  on public.leads to authenticated;
grant update (stage, wa_at, call_at, d3_at, d7_at, meeting_at, next_step, due_at, notes,
              message, message_alt, followup_d3, followup_d7, owner_id, skipped_until,
              regen_requested_at, last_activity_at, updated_at)
  on public.leads to authenticated;
-- deal_value_inr: no grant at all. Admin server actions write it with the service role (Step 15).

-- views
revoke all on public.v_pipeline from authenticated;            -- has money; engine only
grant select on public.v_leads_caller, public.v_leads_admin, public.v_today, public.v_followups_due,
                public.v_funnel, public.v_kpis_week, public.v_primary_contact, public.v_top_signal,
                public.v_verified_facts, public.v_costs_daily, public.v_source_health
  to authenticated;   -- base-table RLS still applies: costs and source health stay admin-only

-- activities
create policy activities_read on public.activities for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy activities_insert on public.activities for insert to authenticated
  with check (public.auth_role() in ('admin','caller') and user_id = auth.uid() and source = 'app');

-- feedback
create policy feedback_read on public.feedback for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy feedback_insert on public.feedback for insert to authenticated
  with check (user_id = auth.uid() and public.auth_role() in ('admin','caller','viewer'));
create policy feedback_update_own on public.feedback for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- suppression
create policy suppression_read on public.suppression for select to authenticated
  using (public.auth_role() in ('admin','caller'));
create policy suppression_insert on public.suppression for insert to authenticated
  with check (public.auth_role() in ('admin','caller') and added_by = auth.uid());
create policy suppression_delete on public.suppression for delete to authenticated
  using (public.auth_role() = 'admin');

-- operations: admin read; admin can switch a source on or off
create policy runs_admin    on public.runs        for select to authenticated using (public.auth_role() = 'admin');
create policy costs_admin   on public.costs       for select to authenticated using (public.auth_role() = 'admin');
create policy batches_admin on public.llm_batches for select to authenticated using (public.auth_role() = 'admin');
create policy health_admin  on public.source_health for select to authenticated using (public.auth_role() = 'admin');
create policy health_admin_update on public.source_health for update to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

-- golden labels, custom queries, inbox: admin
create policy golden_admin on public.golden_labels for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy custom_queries_admin on public.custom_queries for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy inbox_admin on public.inbox_posts for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

-- saved views: your own, plus any marked shared
create policy saved_views_read on public.saved_views for select to authenticated
  using (user_id = auth.uid() or shared);
create policy saved_views_own on public.saved_views for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- No policies at all (engine only): sheet_snapshots, llm_cache, llm_batch_reservations.

-- 4. Functions ------------------------------------------------------------------
revoke all on function public.db_size_mb() from public, anon;
grant execute on function public.db_size_mb() to authenticated, service_role;

-- 5. Storage: private buckets -----------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('proposals', 'proposals', false, 20971520,          -- 20 MB
   array['application/pdf','image/png','image/jpeg',
         'application/vnd.openxmlformats-officedocument.wordprocessingml.document']),
  ('backups', 'backups', false, 52428800, null)        -- 50 MB, the free-plan upload limit (verify at build)
on conflict (id) do nothing;

create policy proposals_read on storage.objects for select to authenticated
  using (bucket_id = 'proposals' and public.auth_role() in ('admin','caller'));
create policy proposals_upload on storage.objects for insert to authenticated
  with check (bucket_id = 'proposals' and public.auth_role() in ('admin','caller'));
create policy proposals_delete on storage.objects for delete to authenticated
  using (bucket_id = 'proposals' and public.auth_role() = 'admin');
-- 'backups' has no policies: only the service role (nlead backup, Step 14) can use it.
