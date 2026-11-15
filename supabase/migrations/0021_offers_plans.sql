-- 0021_offers_plans.sql : what we offer each startup, and the personal plan page (15 Nov 2026)
--
-- offers        the 8 productized offers (one best match per lead, plus a backup)
-- lead_offers   the engine's pick for a lead: rank 1 (main) and 2 (backup), the "why now" and the evidence ids
-- case_studies  short proof pages the emails link to (the founder approves each)
-- plan_pages    a personal 1-page plan or proposal per lead, served at /p/<token> without sign-in: a 128-bit
--               random token, never indexed, revocable, expires after 90 days
-- proposals     AI-drafted proposals after a call (the founder reviews and sends)

create table if not exists public.offers (
  key           text primary key,
  name          text not null,
  best_for      text not null,
  promise       text not null,
  timeline      text not null,
  typical_range jsonb not null default '{}'::jsonb,   -- {"usd": [3000, 8000], "inr": [150000, 500000]}
  active        boolean not null default true,
  sort          integer not null default 0
);

insert into public.offers (key, name, best_for, promise, timeline, typical_range, sort) values
  ('launch_kit', 'Launch kit', 'Idea stage, no product yet',
   'A landing page, waitlist and clickable demo that make the idea real for users and investors', '1 week',
   '{"usd": [500, 1500], "inr": [40000, 120000]}', 1),
  ('mvp_sprint', 'MVP sprint', 'Pre-seed, non-technical founders',
   'A polished, working first version of the product, built with AI speed and fixed scope', '4 to 6 weeks',
   '{"usd": [3000, 12000], "inr": [150000, 600000]}', 2),
  ('nocode_to_app', 'No-code to real app', 'Outgrowing Bubble, Webflow, Softr, Glide or Lovable',
   'The same product rebuilt as a real, fast, scalable app the team owns', '4 to 8 weeks',
   '{"usd": [4000, 15000], "inr": [200000, 800000]}', 3),
  ('ai_feature', 'AI feature sprint', 'Product live, no AI yet',
   'One AI feature users notice, shipped into the existing product', '2 to 3 weeks',
   '{"usd": [2000, 8000], "inr": [100000, 400000]}', 4),
  ('mobile_app', 'Mobile app from the web app', 'Web product live, no app',
   'iOS and Android apps from the existing product', '4 to 6 weeks',
   '{"usd": [4000, 12000], "inr": [200000, 600000]}', 5),
  ('tech_team', 'Your tech team, monthly', 'Hiring a first engineer or CTO',
   'A senior dev and AI team on call every month, instead of a long hire', 'Monthly',
   '{"usd_month": [1500, 6000], "inr_month": [80000, 300000]}', 6),
  ('ai_ops', 'AI ops automation', 'Traction with too much manual work',
   'The manual busywork automated with AI workflows', '2 to 4 weeks',
   '{"usd": [1500, 6000], "inr": [80000, 300000]}', 7),
  ('product_care', 'Product care, monthly', 'After every build',
   'Fixes, updates and small features every month', 'Monthly',
   '{"usd_month": [300, 1500], "inr_month": [20000, 80000]}', 8)
on conflict (key) do nothing;

create table if not exists public.lead_offers (
  lead_id    uuid not null references public.leads(id) on delete cascade,
  rank       smallint not null check (rank in (1, 2)),
  offer_key  text not null references public.offers(key),
  why_now    text,
  cited_ids  text[] not null default '{}',
  model      text,
  created_at timestamptz not null default now(),
  primary key (lead_id, rank)
);

create table if not exists public.case_studies (
  id         uuid primary key default gen_random_uuid(),
  slug       text not null unique,
  title      text not null,
  client     text,                                  -- how the client may be named (often "a seed-stage healthtech")
  offer_key  text references public.offers(key),
  summary    text not null,
  body       jsonb not null default '{}'::jsonb,
  published  boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.plan_pages (
  token           text primary key check (length(token) >= 22),
  lead_id         uuid not null references public.leads(id) on delete cascade,
  kind            text not null default 'plan' check (kind in ('plan', 'proposal')),
  content         jsonb not null,
  status          text not null default 'live' check (status in ('live', 'revoked', 'expired')),
  expires_at      timestamptz not null default now() + interval '90 days',
  views           integer not null default 0,
  first_viewed_at timestamptz,
  last_viewed_at  timestamptz,
  created_at      timestamptz not null default now()
);
create index if not exists plan_pages_lead_idx on public.plan_pages (lead_id);

create table if not exists public.proposals (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references public.leads(id) on delete cascade,
  plan_token text references public.plan_pages(token) on delete set null,
  call_notes text,
  content    jsonb not null default '{}'::jsonb,
  status     text not null default 'draft' check (status in ('draft','approved','sent','accepted','declined')),
  model      text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists proposals_lead_idx on public.proposals (lead_id);

alter table public.offers enable row level security;
alter table public.lead_offers enable row level security;
alter table public.case_studies enable row level security;
alter table public.plan_pages enable row level security;
alter table public.proposals enable row level security;
create policy offers_read on public.offers for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy lead_offers_read on public.lead_offers for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy case_studies_read on public.case_studies for select to authenticated
  using (public.auth_role() in ('admin','caller','viewer'));
create policy case_studies_admin_write on public.case_studies for all to authenticated
  using (public.auth_role() = 'admin') with check (public.auth_role() = 'admin');
create policy plan_pages_read on public.plan_pages for select to authenticated
  using (public.auth_role() in ('admin','caller'));
create policy proposals_read on public.proposals for select to authenticated
  using (public.auth_role() in ('admin','caller'));
create policy proposals_update on public.proposals for update to authenticated
  using (public.auth_role() in ('admin','caller')) with check (public.auth_role() in ('admin','caller'));
-- Plan pages are served to the public by the server with the service role; anonymous users get nothing here.
-- New tables get no grants by default (0003): reads for the app, writes only where a policy allows them.
grant select on public.offers, public.lead_offers, public.case_studies, public.plan_pages, public.proposals
  to authenticated;
grant insert, update, delete on public.case_studies to authenticated;
grant update (call_notes, content, status, updated_at) on public.proposals to authenticated;
