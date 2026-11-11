-- 0001_core.sql : core schema for nument-leads
-- Apply with: npx supabase db push (dev in Step 2, prod in Step 21)
--         or: cd engine && uv run nlead db migrate (records the same history table)

create extension if not exists pgcrypto with schema extensions;
create extension if not exists pg_trgm  with schema extensions;
create extension if not exists unaccent with schema extensions;

-- =========================================================================
-- Helper
-- =========================================================================
create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- =========================================================================
-- settings: key/value configuration read by engine and app (keys in 0004)
-- =========================================================================
create table public.settings (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
create trigger settings_updated_at before update on public.settings
  for each row execute function public.set_updated_at();

-- =========================================================================
-- segments: one row per domain x country; config is a copy of the YAML (Step 3)
-- =========================================================================
create table public.segments (
  id             text primary key check (id ~ '^[a-z0-9]+-[a-z]{2}$'),
  domain         text not null check (domain in
                   ('clinics','realestate','education','d2c','hospitality',
                    'auto','finance','wellness','firms')),
  country        char(2) not null check (country ~ '^[a-z]{2}$'),
  display_name   text not null,
  enabled        boolean not null default false,
  daily_quota    integer not null default 0 check (daily_quota >= 0),
  config         jsonb not null default '{}'::jsonb,
  config_version text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint segments_id_matches check (id = domain || '-' || country)
);
create trigger segments_updated_at before update on public.segments
  for each row execute function public.set_updated_at();

-- =========================================================================
-- businesses: one real company after dedupe (Step 6)
-- =========================================================================
create table public.businesses (
  id                uuid primary key default gen_random_uuid(),
  segment_id        text not null references public.segments(id)
                      on update cascade on delete restrict,
  name              text not null,
  norm_name         text not null,
  website           text,
  web_domain        text,
  country           char(2) not null,
  city              text,
  locality          text,
  address           text,
  lat               double precision check (lat between -90 and 90),
  lng               double precision check (lng between -180 and 180),
  category          text,                 -- raw source category (Overture code or Places type)
  subcategory       text,                 -- our class: a ticket_class key of the segment (Step 3)
  place_id          text,
  overture_id       text,
  branches_count    integer check (branches_count >= 0),
  staff_count       integer check (staff_count >= 0),
  review_count      integer check (review_count >= 0),            -- Places content: 30 days max (A.4.4)
  rating            numeric(2,1) check (rating between 0 and 5),   -- Places content: 30 days max
  places_fetched_at timestamptz,
  status            text not null default 'candidate' check (status in
                      ('candidate','queued','researched','qualified',
                       'rejected','suppressed','dormant')),
  reject_reason     text,
  queued_at         timestamptz,          -- set by the pre-filter (Step 8)
  queue_priority    real,                 -- higher is researched first (Step 8.7)
  extra             jsonb not null default '{}'::jsonb,   -- small extras (registry ids and similar)
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now(),
  researched_at     timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create unique index businesses_place_id_uq    on public.businesses (place_id)    where place_id is not null;
create unique index businesses_overture_id_uq on public.businesses (overture_id) where overture_id is not null;
create unique index businesses_seg_domain_uq  on public.businesses (segment_id, web_domain) where web_domain is not null;
create index businesses_seg_status_idx        on public.businesses (segment_id, status);
create index businesses_seg_city_idx          on public.businesses (segment_id, city);
create index businesses_queue_idx             on public.businesses (queue_priority desc) where status = 'queued';
create index businesses_norm_name_trgm        on public.businesses using gin (norm_name extensions.gin_trgm_ops);
create trigger businesses_updated_at before update on public.businesses
  for each row execute function public.set_updated_at();

-- =========================================================================
-- source_records: raw records from each source, linked to a business
-- =========================================================================
create table public.source_records (
  id          uuid primary key default gen_random_uuid(),
  source      text not null,
  source_key  text not null,              -- the id inside that source
  business_id uuid references public.businesses(id) on delete set null,
  payload     jsonb not null default '{}'::jsonb,   -- keep slim: only fields we use
  fetched_at  timestamptz not null default now(),
  constraint source_records_uq unique (source, source_key),
  -- A new registry adapter adds its key here in a new migration on the day it goes live (2.6.1).
  -- legacy and legacy_skip are written once by `nlead migrate-legacy` (Step 20).
  constraint source_records_source_known check (source in
    ('overture','places','art_registry','osm','apna','grounded_search',
     'gdelt','careers_watch','adzuna','practo','legacy','legacy_skip'))
);
create index source_records_business_idx on public.source_records (business_id);

-- =========================================================================
-- signals: dated evidence of need (A.12.3)
-- =========================================================================
create table public.signals (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  type        text not null check (type in
                ('public_ask','tender','hiring_builder','hiring_frontdesk',
                 'review_pain','ads_running','no_booking','slow_site',
                 'new_place','new_branch','news','funding')),
  category    text not null check (category in ('stated_need','visible_pain','growth','money')),
  points      numeric(5,2) not null default 0,   -- effective points (segment override applied, Step 7)
  observed_at timestamptz not null,
  expires_at  timestamptz not null,
  source      text not null,                     -- watcher name, or 'manual' for ads_running from the app
  url         text,
  quote       text,
  details     jsonb not null default '{}'::jsonb,
  dedupe_key  text not null unique,              -- for example 'apna:job:123456'
  created_at  timestamptz not null default now(),
  constraint signals_expiry_after_observed check (expires_at > observed_at)
);
create index signals_business_active_idx on public.signals (business_id, expires_at);
create index signals_type_idx on public.signals (type, observed_at desc);

-- =========================================================================
-- pages: fetched web pages (retention in Step 18.2.2)
-- =========================================================================
create table public.pages (
  id             uuid primary key default gen_random_uuid(),
  business_id    uuid references public.businesses(id) on delete cascade,
  url            text not null unique,
  fetched_at     timestamptz not null default now(),
  http_status    integer,
  render_mode    text not null default 'http' check (render_mode in ('http','browser')),
  title          text,
  text           text,                  -- cleaned main text, max 20,000 characters (Step 9)
  text_hash      text,                  -- sha256 of text, kept after text is deleted
  robots_allowed boolean not null default true
);
create index pages_business_idx on public.pages (business_id);
create index pages_fetched_idx  on public.pages (fetched_at);

-- =========================================================================
-- facts: extracted facts, each with quote and url, verified by code (Step 10)
-- =========================================================================
create table public.facts (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,
  field        text not null,           -- for example decision_maker, staff_or_doctors, price_point
  value        jsonb not null,
  quote        text,
  url          text,
  page_id      uuid references public.pages(id) on delete set null,
  model        text,                    -- model that extracted it, or 'rule'
  verified     boolean not null default false,
  verify_score numeric(5,2),            -- 0 to 100 match score; -1 = lost a conflict (Step 10)
  verified_at  timestamptz,
  created_at   timestamptz not null default now()
);
create index facts_business_field_idx on public.facts (business_id, field, created_at desc);

-- =========================================================================
-- contacts: phones, emails, decision makers
-- =========================================================================
create table public.contacts (
  id                uuid primary key default gen_random_uuid(),
  business_id       uuid not null references public.businesses(id) on delete cascade,
  name              text,
  role              text,
  phone_e164        text check (phone_e164 ~ '^\+[1-9][0-9]{6,14}$'),
  phone_type        text not null default 'unknown'
                      check (phone_type in ('mobile','landline','tollfree','unknown')),
  email             text,
  source            text not null check (source in ('website','google_listing','registry','other')),
  source_url        text,
  quote             text,
  is_decision_maker boolean not null default false,
  verified          boolean not null default false,
  verified_at       timestamptz,          -- the 30-day Google listing rule (Step 10)
  do_not_contact    boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint contacts_has_something check (phone_e164 is not null or email is not null or name is not null)
);
create unique index contacts_business_phone_uq on public.contacts (business_id, phone_e164) where phone_e164 is not null;
create unique index contacts_business_email_uq on public.contacts (business_id, lower(email)) where email is not null;
create index contacts_phone_idx on public.contacts (phone_e164);
create trigger contacts_updated_at before update on public.contacts
  for each row execute function public.set_updated_at();

-- =========================================================================
-- scores: every scoring run is kept
-- =========================================================================
create table public.scores (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  version     text not null,             -- SCORE_VERSION from score.py, for example 's1.0' (Step 11)
  fit         smallint not null check (fit between 0 and 3),
  can_pay     numeric(5,2) not null default 0 check (can_pay between 0 and 30),
  intent      numeric(5,2) not null default 0 check (intent between 0 and 40),
  reach       numeric(4,2) not null default 0 check (reach between 0 and 1),
  total       numeric(5,2) not null check (total between 0 and 100),
  grade       char(1) not null check (grade in ('A','B','C','D')),
  pitch_mode  text not null check (pitch_mode in ('stated_need','visible_pain','fit_only')),
  reasons     jsonb not null default '{}'::jsonb,
  judge_grade char(1) check (judge_grade in ('A','B','C','D')),
  judge_note  text,
  judge_model text,
  computed_at timestamptz not null default now()
);
create index scores_business_time_idx on public.scores (business_id, computed_at desc);

-- =========================================================================
-- profiles: app users and roles (one row per auth.users row)
-- =========================================================================
create table public.profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  full_name  text,
  role       text not null default 'viewer' check (role in ('admin','caller','viewer')),
  created_at timestamptz not null default now()
);

-- Every new auth user gets a 'viewer' profile. An admin then sets the role (Step 15).
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id, full_name, role)
  values (new.id,
          coalesce(new.raw_user_meta_data ->> 'full_name', split_part(new.email, '@', 1)),
          'viewer')
  on conflict (user_id) do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Role of the logged-in user ('none' when not logged in or no profile). Used by every policy.
create or replace function public.auth_role() returns text
language sql stable security definer set search_path = public as $$
  select coalesce((select role from public.profiles where user_id = auth.uid()), 'none')
$$;

-- =========================================================================
-- leads: graded businesses with a message and a stage
-- =========================================================================
create table public.leads (
  id                  uuid primary key default gen_random_uuid(),
  business_id         uuid not null references public.businesses(id) on delete restrict,
  segment_id          text not null references public.segments(id) on update cascade on delete restrict,
  score_id            uuid references public.scores(id) on delete set null,
  grade               char(1) not null check (grade in ('A','B','C','D')),
  pitch_mode          text not null check (pitch_mode in ('stated_need','visible_pain','fit_only')),
  test_group          text,              -- '{segment_id}:{pitch_mode}:{angle}' (A.12.4)
  angle               text,
  channel             text not null default 'whatsapp' check (channel in ('whatsapp','email','form')),
  message             text,              -- WhatsApp or contact-form text
  message_alt         text,
  email_subject       text,              -- only when channel = 'email' (Step 12)
  email_body          text,
  followup_d3         text,
  followup_d7         text,
  message_model       text,
  message_check_score numeric(4,1),      -- 0 to 10 from the critic (Step 12)
  stage               text not null default 'new' check (stage in
                        ('new','contacted','talking','discovery_booked','discovery_done',
                         'proposal_sent','won','retainer','lost','not_now','not_a_fit','wrong_contact')),
  owner_id            uuid references public.profiles(user_id) on delete set null,
  wa_at               date,              -- first message sent (IST date)
  call_at             date,
  d3_at               date,
  d7_at               date,
  meeting_at          timestamptz,
  next_step           text,
  due_at              date,
  skipped_until       timestamptz,       -- "Skip" in the app hides the lead from Today until then
  regen_requested_at  timestamptz,       -- the app asks the engine for a new message
  deal_value_inr      numeric(12,2) check (deal_value_inr >= 0),   -- money: see 2.8.3
  notes               text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  last_activity_at    timestamptz not null default now()
);
-- One open lead per business. Closed stages may repeat later (a new cycle).
create unique index leads_one_open_per_business on public.leads (business_id)
  where stage not in ('won','retainer','lost','not_now','not_a_fit','wrong_contact');
create index leads_stage_idx         on public.leads (stage);
create index leads_segment_grade_idx on public.leads (segment_id, grade);
create index leads_due_idx           on public.leads (due_at) where due_at is not null;
create index leads_regen_idx         on public.leads (regen_requested_at) where regen_requested_at is not null;

-- Keep updated_at and last_activity_at right, and fill the first-message date.
create or replace function public.leads_before_write() returns trigger
language plpgsql as $$
begin
  if tg_op = 'UPDATE' then
    new.updated_at := now();
    if new.stage is distinct from old.stage then
      new.last_activity_at := now();
    end if;
  end if;
  -- Marking Contacted without a date means "sent today" (the 17 Oct 2026 sheet bug).
  if new.stage = 'contacted' and new.wa_at is null then
    new.wa_at := (now() at time zone 'Asia/Kolkata')::date;
  end if;
  return new;
end $$;
create trigger leads_before_write before insert or update on public.leads
  for each row execute function public.leads_before_write();

-- =========================================================================
-- activities: the lead timeline (app, sheet and engine all write here)
-- =========================================================================
create table public.activities (
  id      uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  user_id uuid default auth.uid() references public.profiles(user_id) on delete set null,
  source  text not null check (source in ('app','sheet','engine')),
  type    text not null check (type in (
            -- written by the lead triggers only (rule 2.5.9)
            'lead_created','stage_change','grade_change','message_edited',
            -- written by code
            'message_flagged','regen_request','sent','followup_sent','reply','call','meeting',
            'proposal','proposal_upload','note','edit','feedback','skip','wrong_contact','undo',
            'merge','ai_output','conflict_overridden','unknown_stage')),
  at      timestamptz not null default now(),
  payload jsonb not null default '{}'::jsonb
);
create index activities_lead_time_idx on public.activities (lead_id, at desc);
create index activities_type_time_idx on public.activities (type, at desc);

-- Log creation, stage changes, grade changes and app edits of the message.
create or replace function public.leads_after_write() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_source text := coalesce(nullif(current_setting('app.source', true), ''),
                            case when auth.uid() is null then 'engine' else 'app' end);
  v_ctx    jsonb := coalesce(nullif(current_setting('app.context', true), '')::jsonb, '{}'::jsonb);
begin
  if tg_op = 'INSERT' then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'lead_created',
            jsonb_build_object('grade', new.grade, 'pitch_mode', new.pitch_mode,
                               'channel', new.channel, 'test_group', new.test_group) || v_ctx);
    return new;
  end if;
  if new.stage is distinct from old.stage then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'stage_change',
            jsonb_build_object('from', old.stage, 'to', new.stage) || v_ctx);
  end if;
  if new.grade is distinct from old.grade then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'grade_change',
            jsonb_build_object('from', old.grade, 'to', new.grade) || v_ctx);
  end if;
  if auth.uid() is not null and (new.message is distinct from old.message
                                 or new.message_alt is distinct from old.message_alt) then
    insert into public.activities (lead_id, user_id, source, type, payload)
    values (new.id, auth.uid(), v_source, 'message_edited', v_ctx);
  end if;
  return new;
end $$;
create trigger leads_after_write after insert or update on public.leads
  for each row execute function public.leads_after_write();

-- =========================================================================
-- feedback: thumbs up or down on lead quality (Step 16)
-- =========================================================================
create table public.feedback (
  id      uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  user_id uuid default auth.uid() references public.profiles(user_id) on delete set null,
  rating  smallint not null check (rating in (-1, 1)),
  reason  text,
  at      timestamptz not null default now(),
  constraint feedback_one_per_user unique (lead_id, user_id)
);

-- =========================================================================
-- suppression: never contact these again (kept forever, Step 18)
-- =========================================================================
create table public.suppression (
  id         uuid primary key default gen_random_uuid(),
  phone_e164 text check (phone_e164 ~ '^\+[1-9][0-9]{6,14}$'),
  email      text,
  web_domain text,
  reason     text not null,      -- opt_out, wrong_contact, competitor, founder_skip, legal
  added_by   uuid default auth.uid() references public.profiles(user_id) on delete set null,
  added_at   timestamptz not null default now(),
  constraint suppression_has_key check (phone_e164 is not null or email is not null or web_domain is not null)
);
create unique index suppression_phone_uq  on public.suppression (phone_e164)   where phone_e164 is not null;
create unique index suppression_email_uq  on public.suppression (lower(email)) where email is not null;
create unique index suppression_domain_uq on public.suppression (web_domain)   where web_domain is not null;

-- =========================================================================
-- Operations: runs, costs, AI batches, AI cache, source health
-- =========================================================================
create table public.runs (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null check (kind in ('night','morning','sheet_sync','weekly','monthly','manual')),
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null default 'running' check (status in ('running','ok','partial','failed')),
  stats       jsonb not null default '{}'::jsonb,
  error       text
);
create index runs_kind_time_idx on public.runs (kind, started_at desc);

create table public.costs (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid references public.runs(id) on delete set null,
  provider      text not null check (provider in
                  ('gemini','openai','cache','google_places','google_search','pagespeed','other')),
  model         text,
  task          text not null,
  input_tokens  bigint not null default 0,
  output_tokens bigint not null default 0,
  calls         integer not null default 1,
  usd           numeric(12,6) not null default 0,
  inr           numeric(12,2) not null default 0,
  fallback_from text,             -- the planned provider when a fallback answered (Step 4)
  at            timestamptz not null default now()
);
create index costs_at_idx on public.costs (at);

create table public.llm_batches (
  id                uuid primary key default gen_random_uuid(),
  provider          text not null check (provider in ('gemini','openai')),
  provider_batch_id text not null,
  task              text not null,
  status            text not null default 'submitted' check (status in
                      ('submitted','running','completed','failed','expired','cancelled')),
  item_count        integer not null default 0,
  submitted_at      timestamptz not null default now(),
  completed_at      timestamptz,
  result_ref        text,          -- provider file name or local path of the results
  constraint llm_batches_uq unique (provider, provider_batch_id)
);

-- Money held for a submitted batch until its results are collected (Step 4).
create table public.llm_batch_reservations (
  id           bigserial primary key,
  llm_batch_id uuid references public.llm_batches(id) on delete cascade,
  reserved_inr numeric not null,
  released     boolean not null default false,
  created_at   timestamptz not null default now()
);

-- Cached AI answers (Step 4). The night run deletes expired rows.
create table public.llm_cache (
  key        text primary key,
  task       text not null,
  model      text not null,
  response   jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index llm_cache_expires_idx on public.llm_cache (expires_at);

-- One row per source, plus 'llm:gemini' and 'llm:openai' for the AI circuit breakers (Step 4).
create table public.source_health (
  source         text primary key,
  enabled        boolean not null default true,
  last_ok_at     timestamptz,
  last_error_at  timestamptz,
  last_error     text,
  blocked_until  timestamptz,
  recent_blocks  timestamptz[] not null default '{}',   -- newest first, keep 10 (Steps 5 and 18 count them)
  requests_today integer not null default 0,
  requests_day   date not null default ((now() at time zone 'Asia/Kolkata')::date)  -- day of requests_today
);

-- =========================================================================
-- sheet_snapshots: what we last wrote to each sheet (two-way sync, Step 13)
-- =========================================================================
create table public.sheet_snapshots (
  sheet      text not null check (sheet in ('master','caller')),
  lead_id    uuid not null references public.leads(id) on delete cascade,
  values     jsonb not null,
  written_at timestamptz not null default now(),
  primary key (sheet, lead_id)
);

-- =========================================================================
-- golden_labels, custom_queries, inbox_posts, saved_views
-- =========================================================================
create table public.golden_labels (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  label       text not null check (label in ('good','bad')),
  reasons     text,
  labeled_by  uuid default auth.uid() references public.profiles(user_id) on delete set null,
  at          timestamptz not null default now(),
  constraint golden_one_per_labeler unique (business_id, labeled_by)
);

create table public.custom_queries (
  id         uuid primary key default gen_random_uuid(),
  segment_id text not null references public.segments(id) on update cascade,
  query      text not null,
  -- A.13.5 rule 9 statuses, plus the earlier Step 2 ones so no step's code is refused.
  status     text not null default 'new' check (status in
               ('new','processing','researched','lead_created','rejected',
                'running','done','failed')),
  created_by uuid default auth.uid() references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.inbox_posts (
  id         uuid primary key default gen_random_uuid(),
  url        text,
  text       text not null,
  segment_id text references public.segments(id) on update cascade,
  status     text not null default 'new' check (status in
               ('new','processing','processed','researched','lead_created','rejected')),
  lead_id    uuid references public.leads(id) on delete set null,   -- the lead made from this post
  created_by uuid default auth.uid() references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.saved_views (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references public.profiles(user_id) on delete cascade,
  name       text not null,
  query      jsonb not null default '{}'::jsonb,   -- filters, sort and columns of the Leads page
  shared     boolean not null default false,
  created_at timestamptz not null default now()
);
create index saved_views_user_idx on public.saved_views (user_id);
