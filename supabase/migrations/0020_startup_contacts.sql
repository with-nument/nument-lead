-- 0020_startup_contacts.sql : what we know about each startup, and the founder's email (15 Nov 2026)
--
-- startup_profiles holds the qualification the engine works out for each startup, every answer backed by
-- evidence ids (facts or signals) or left 'unknown': is it a real startup, how big is the team, does it have
-- a tech team, can it pay, what is the product, how fresh is it.
-- Founder emails come from published sources first, then a name-pattern guess checked without sending
-- (founder approved, 15 Nov 2026). Each contact email now says how it was found and how sure we are.

create table if not exists public.startup_profiles (
  business_id        uuid primary key references public.businesses(id) on delete cascade,
  is_startup         boolean,
  is_startup_why     text,
  team_size          integer check (team_size is null or team_size >= 0),
  team_size_source   text,                      -- team_page, news, job_post, snippet, filing, list
  team_size_evidence text[] not null default '{}',
  tech_team          text not null default 'unknown'
                       check (tech_team in ('none','lone_cto','has_engineers','unknown')),
  tech_team_evidence text[] not null default '{}',
  can_pay            text not null default 'unknown' check (can_pay in ('yes','likely','no','unknown')),
  can_pay_evidence   text[] not null default '{}',
  product_status     text not null default 'unknown'
                       check (product_status in ('idea','landing','waitlist','no_code','web_app','mobile_app','unknown')),
  no_code_platform   text,
  uses_ai            boolean,
  funding_usd        numeric(14,0),
  funding_round      text,
  funding_at         date,
  domain_created_at  date,
  first_seen_at      date,
  checked_at         timestamptz,
  updated_at         timestamptz not null default now()
);

alter table public.contacts
  add column if not exists email_status text not null default 'unknown'
    constraint contacts_email_status_known check (email_status in ('verified','likely','unknown','invalid')),
  add column if not exists email_origin text
    constraint contacts_email_origin_known check (email_origin is null or email_origin in
      ('published','archive','snippet','store','filing','post','guess')),
  add column if not exists email_pattern text,
  add column if not exists email_checked_at timestamptz;

create table if not exists public.email_domains (
  domain      text primary key,
  mx_provider text,                             -- google, microsoft, other, none
  catch_all   boolean,
  checked_at  timestamptz not null default now()
);

create table if not exists public.email_checks (
  email      text primary key,
  result     text not null check (result in ('deliverable','undeliverable','risky','unknown')),
  provider   text not null,                     -- quickemailverification, myemailverifier
  raw        jsonb not null default '{}'::jsonb,
  checked_at timestamptz not null default now()
);

-- Engine-only tables: row level security on, no policies (the service role bypasses it).
alter table public.email_domains enable row level security;
alter table public.email_checks enable row level security;
alter table public.startup_profiles enable row level security;
create policy startup_profiles_read on public.startup_profiles for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
-- New tables get no grants by default (0003): the app reads profiles; email_domains and email_checks stay engine only.
grant select on public.startup_profiles to authenticated;

-- The best contact first: a verified founder email, then the owner's own number, then everything else.
create or replace view public.v_primary_contact with (security_invoker = true) as
select distinct on (c.business_id)
  c.business_id, c.id as contact_id, c.name, c.role, c.phone_e164, c.phone_type,
  c.email, c.source, c.source_url, c.is_decision_maker, c.verified, c.line, c.line_why
from public.contacts c
where not c.do_not_contact
  and (c.phone_e164 is not null or c.email is not null)
  and not exists (select 1 from public.suppression su where su.phone_e164 = c.phone_e164)
  and not exists (select 1 from public.suppression su where lower(su.email) = lower(c.email))
  and coalesce(c.email_status, 'unknown') <> 'invalid'
order by c.business_id,
         case
           when c.line = 'owner' and c.email is not null and c.email_status = 'verified' then 0
           when c.line = 'owner' and c.phone_e164 is not null then 1
           when c.line = 'owner' and c.email is not null then 2
           when c.line = 'other' and c.phone_type = 'mobile' then 3
           when c.line = 'front_desk' and c.phone_e164 is not null then 4
           when c.line <> 'bot' and c.email is not null then 5
           when c.line <> 'bot' then 6
           else 7
         end,
         c.verified desc,
         (c.source = 'website') desc,
         c.created_at;
