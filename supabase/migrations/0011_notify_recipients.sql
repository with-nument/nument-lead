-- 0011_notify_recipients.sql : who gets the engine's emails (founder request, 12 Nov 2026)
--
-- Admins manage the list on Settings > Email recipients. Each person picks what they get: the morning list,
-- alerts (a failed run, spend near the daily cap) and the weekly report. The engine reads the list with its
-- own connection and sends every recipient a separate email. While the table is empty the engine falls back
-- to ALERT_EMAIL. Nothing is seeded.

create table if not exists public.notify_recipients (
  id         uuid primary key default gen_random_uuid(),
  email      text not null,
  name       text,
  morning    boolean not null default true,
  alerts     boolean not null default true,
  weekly     boolean not null default true,
  active     boolean not null default true,
  created_by uuid default auth.uid() references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default now(),
  constraint notify_recipients_email_lower check (email = lower(btrim(email))),
  constraint notify_recipients_email_shape check (length(email) <= 254 and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  constraint notify_recipients_name_len check (name is null or length(name) <= 80)
);
create unique index if not exists notify_recipients_email_uq on public.notify_recipients (email);

-- Access: admins read and write; callers, viewers and visitors get nothing. The engine uses its own role.
alter table public.notify_recipients enable row level security;

create policy notify_recipients_admin on public.notify_recipients for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');

revoke all on public.notify_recipients from anon;
grant select, insert, update, delete on public.notify_recipients to authenticated;
