-- 0006_cost_views.sql : spend and quota views for the budget guard (Step 19.4)
--
-- v_costs_daily belongs to 0002 and is not recreated here (A.13.5 rule 2).
-- Days and months are IST. The filters compare `at` with the IST day or month start as a timestamptz,
-- which gives the same rows as comparing IST dates but lets costs_at_idx answer them: the budget guard
-- reads these views before every paid call.
-- Engine only: the app does not read them, so there is no grant to app users (2.8.4).

-- Today's spend.
create or replace view public.v_spend_today with (security_invoker = true) as
select coalesce(sum(c.inr), 0)::numeric(12,2) as inr,
       coalesce(sum(c.usd), 0)::numeric(12,4) as usd
from public.costs c
where c.at >= (date_trunc('day', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata');

-- Calls per provider and task today (daily quotas).
create or replace view public.v_quota_today with (security_invoker = true) as
select c.provider, c.task, sum(c.calls)::int as calls
from public.costs c
where c.at >= (date_trunc('day', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata')
group by c.provider, c.task;

-- Calls per provider and task this month (free monthly allowances).
create or replace view public.v_quota_month with (security_invoker = true) as
select c.provider, c.task, sum(c.calls)::int as calls
from public.costs c
where c.at >= (date_trunc('month', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata')
group by c.provider, c.task;
