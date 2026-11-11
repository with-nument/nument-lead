-- 0007_learning.sql : storage for the learning loop and reports (Step 16)

-- =========================================================================
-- v_lead_funnel: the highest stage each lead ever reached, for the learning maths (16.1.4)
-- A lead that went Contacted, Talking, then Lost still counts as contacted and replied.
-- Engine only (the app reads v_funnel from 0002), so there is no grant to app users.
-- =========================================================================
create or replace view public.v_lead_funnel with (security_invoker = true) as
with stage_rank(stage, rnk) as (
  values ('new',0),('contacted',1),('talking',2),('discovery_booked',3),('discovery_done',3),
         ('proposal_sent',4),('won',5),('retainer',5),
         ('lost',null),('not_now',null),('not_a_fit',null),('wrong_contact',null)
),
hist as (
  select a.lead_id, max(sr.rnk) as max_rank_hist,
         min(a.at) filter (where a.payload->>'to' = 'contacted') as first_contacted_at
  from public.activities a
  join stage_rank sr on sr.stage = a.payload->>'to'
  where a.type = 'stage_change'
  group by a.lead_id
)
select l.id as lead_id, l.segment_id, b.country, l.pitch_mode, l.angle, l.test_group, l.grade,
       coalesce(l.wa_at, h.first_contacted_at) as contacted_at,
       greatest(coalesce(h.max_rank_hist,0), coalesce(sr.rnk,0),
                case when l.wa_at is not null then 1 else 0 end) as max_rank,
       (l.stage = 'wrong_contact') as is_wrong_contact,
       l.stage
from public.leads l
join public.businesses b on b.id = l.business_id
left join hist h on h.lead_id = l.id
left join stage_rank sr on sr.stage = l.stage;

-- =========================================================================
-- weight_versions: every change to the scoring weights (16.4.1)
-- Rolling back means copying an older version's weights into settings.score_weights.
-- =========================================================================
create table if not exists public.weight_versions (
  id bigserial primary key,
  version int not null unique,
  weights jsonb not null,
  method text not null check (method in ('defaults','beta_binomial','logistic','manual')),
  reason text,
  diff jsonb,                       -- what changed vs previous version
  created_by text not null default 'engine',
  created_at timestamptz not null default now()
);

-- =========================================================================
-- reports: weekly report, audit, eval and monthly cost (16.6.1)
-- =========================================================================
create table if not exists public.reports (
  id bigserial primary key,
  kind text not null check (kind in ('weekly','audit','eval','monthly_cost')),
  period_start date,
  period_end date,
  content jsonb not null,           -- all numbers, for the app to render
  markdown text not null,           -- the same report as readable text
  created_at timestamptz not null default now()
);
create index if not exists reports_kind_created on public.reports (kind, created_at desc);

-- =========================================================================
-- Access (2.8.4): RLS on, admins read both (Insights and Engine pages). Reports hold money, so callers
-- see the weekly report only as the app renders it on the server without money (16.6.1).
-- The engine writes with the service role.
-- =========================================================================
alter table public.weight_versions enable row level security;
alter table public.reports enable row level security;

create policy weight_versions_admin_read on public.weight_versions for select to authenticated
  using (public.auth_role() = 'admin');
create policy reports_admin_read on public.reports for select to authenticated
  using (public.auth_role() = 'admin');

grant select on public.weight_versions, public.reports to authenticated;
