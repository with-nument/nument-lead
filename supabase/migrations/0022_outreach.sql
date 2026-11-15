-- 0022_outreach.sql : the email autopilot (founder approved, 15 Nov 2026)
--
-- The engine now sends the first email and the follow-ups itself, from one Gmail mailbox ("Nument"), reads the
-- replies, sorts them and drafts answers for the founder. Safety first:
--   * settings outreach.mode is 'off' until the founder switches it on ('manual': he approves every send;
--     'auto': only leads that pass the quality bar go out on their own, everything else waits for review)
--   * sending happens only in prod; in dev every recipient is rewritten to settings outreach.sandbox_to
--   * a warm-up schedule caps each day (10, 15, 20 a day, then +5 a week up to 40)
-- mailboxes       the sending mailbox, its warm-up and health (auto-pause on bounces)
-- email_threads   one open conversation per lead (and one per domain within 90 days)
-- email_messages  the sequence steps (day 0, 3, 7, 12) and every reply, with their status
-- The Gmail refresh token never lives in a table: store_mailbox_token() keeps it in Supabase Vault.

create table if not exists public.mailboxes (
  id                uuid primary key default gen_random_uuid(),
  email             text not null unique,
  display_name      text not null default 'Nument',
  provider          text not null default 'gmail' check (provider in ('gmail')),
  status            text not null default 'disconnected'
                      check (status in ('disconnected','warming','active','paused','error')),
  paused_reason     text,
  warmup_started_on date,
  sent_today        integer not null default 0,
  sent_day          date,
  last_error        text,
  connected_at      timestamptz,
  updated_at        timestamptz not null default now()
);

create table if not exists public.email_threads (
  id              uuid primary key default gen_random_uuid(),
  lead_id         uuid not null references public.leads(id) on delete cascade,
  mailbox_id      uuid references public.mailboxes(id) on delete set null,
  contact_id      uuid references public.contacts(id) on delete set null,
  to_email        text not null,
  to_domain       text not null,
  mode            text not null default 'review' check (mode in ('auto','review')),
  status          text not null default 'open' check (status in ('open','stopped','done')),
  stop_reason     text,
  paused_until    timestamptz,
  gmail_thread_id text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create unique index if not exists email_threads_one_open_per_lead on public.email_threads (lead_id) where status = 'open';
create index if not exists email_threads_domain_idx on public.email_threads (to_domain, created_at desc);

create table if not exists public.email_messages (
  id                        uuid primary key default gen_random_uuid(),
  thread_id                 uuid not null references public.email_threads(id) on delete cascade,
  direction                 text not null check (direction in ('out','in')),
  step                      smallint check (step is null or step in (0, 3, 7, 12)),
  subject                   text,
  body                      text,
  status                    text not null check (status in
                              ('draft','review','approved','queued','sending','sent','failed','cancelled','received')),
  scheduled_for             timestamptz,
  sent_at                   timestamptz,
  rfc_message_id            text,
  gmail_message_id          text,
  classification            text,
  classification_confidence numeric(3,2),
  suggested_reply           text,
  error                     text,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);
create unique index if not exists email_messages_one_per_step on public.email_messages (thread_id, step)
  where direction = 'out' and step is not null;
create index if not exists email_messages_queue_idx on public.email_messages (status, scheduled_for)
  where status in ('approved','queued','sending');
create unique index if not exists email_messages_rfc_idx on public.email_messages (rfc_message_id)
  where rfc_message_id is not null;

-- New timeline events, and two new run kinds.
alter table public.activities drop constraint if exists activities_type_check;
alter table public.activities add constraint activities_type_check check (type in (
  'lead_created','stage_change','grade_change','message_edited',
  'message_flagged','regen_request','sent','followup_sent','reply','call','meeting',
  'proposal','proposal_upload','note','edit','feedback','skip','wrong_contact','undo',
  'merge','ai_output','conflict_overridden','unknown_stage',
  'email_sent','email_received','email_bounced','sequence_stopped','booking','brief','plan_viewed'));

alter table public.runs drop constraint if exists runs_kind_check;
alter table public.runs add constraint runs_kind_check
  check (kind in ('night','morning','midday','outreach','backlog','sheet_sync','weekly','monthly','manual'));

insert into public.settings (key, value) values
  ('outreach.mode', '"off"'::jsonb),                   -- off | manual | auto
  ('outreach.paused', 'false'::jsonb),
  ('outreach.sandbox_to', 'null'::jsonb),              -- dev runs send every email here instead
  ('outreach.warmup', '[10, 15, 20, 25, 30, 35, 40]'::jsonb),   -- daily cap per warm-up week
  ('outreach.auto_min_score', '75'::jsonb),
  ('outreach.auto_min_critic', '9'::jsonb),
  ('outreach.bounce_pause_pct', '3'::jsonb),
  ('email_check.per_day', '150'::jsonb)
on conflict (key) do nothing;

alter table public.mailboxes enable row level security;
alter table public.email_threads enable row level security;
alter table public.email_messages enable row level security;
create policy mailboxes_admin_read on public.mailboxes for select to authenticated
  using (public.auth_role() = 'admin');
create policy email_threads_read on public.email_threads for select to authenticated
  using (public.auth_role() in ('admin','caller'));
create policy email_messages_read on public.email_messages for select to authenticated
  using (public.auth_role() in ('admin','caller'));
-- Approving or editing a draft in the app: only the body, subject and status change, and only for outgoing
-- messages that have not gone out yet (enforced again by the engine before sending).
create policy email_messages_review on public.email_messages for update to authenticated
  using (public.auth_role() in ('admin','caller') and direction = 'out' and status in ('draft','review','approved'))
  with check (public.auth_role() in ('admin','caller') and direction = 'out'
              and status in ('draft','review','approved','cancelled'));
-- New tables get no grants by default (0003). People read, and may edit only a draft's subject, body and status.
grant select on public.mailboxes, public.email_threads, public.email_messages to authenticated;
grant update (subject, body, status, updated_at) on public.email_messages to authenticated;

-- Supabase only (Vault, pg_cron, pg_net); local and CI Postgres skip this part.
do $outer$
begin
  if exists (select 1 from pg_extension where extname = 'supabase_vault') then
    execute $fn$
      create or replace function public.store_mailbox_token(p_email text, p_refresh_token text)
      returns void
      language plpgsql
      security definer
      set search_path = public, vault
      as $body$
      declare
        secret_name text := 'gmail_refresh_token:' || lower(p_email);
        existing uuid;
      begin
        select id into existing from vault.secrets where name = secret_name limit 1;
        if existing is null then
          perform vault.create_secret(p_refresh_token, secret_name, 'Gmail refresh token for the outreach mailbox');
        else
          perform vault.update_secret(existing, p_refresh_token, secret_name);
        end if;
      end;
      $body$
    $fn$;
    execute 'revoke all on function public.store_mailbox_token(text, text) from public, anon, authenticated';
  else
    raise notice '0022_outreach: Supabase Vault not available here, store_mailbox_token skipped';
  end if;

end
$outer$;
-- The 15-minute pg_cron job 'nlead-outreach' (dispatching outreach.yml) is created only when the founder
-- switches outreach on (`nlead outreach schedule on`), so nothing runs every 15 minutes while it is off.
