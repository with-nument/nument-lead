-- 0016_outcomes.sql : the outcomes the learning loop learns from (Phase 4, 13 Nov 2026)
--
-- Learning only works when outcomes are marked, so the app now asks for them at the moment a stage changes.
-- Three lead columns:
--   lost_reason             why a lead closed as Lost or Not now. The app asks for it when it sets either
--                           stage and clears it when the lead moves to any other stage. A stage set from the
--                           sheet has none, so readers use it only while the stage is lost or not_now.
--   retainer_monthly_value  what a retainer client pays a month, in deal_currency (optional).
--   deal_currency           the currency the client pays in. deal_value_inr stays in rupees at the day's rate,
--                           so Money won still adds up; the monthly retainer is kept in the client's currency.
--
-- Access is the same as the columns next to them. lost_reason is read and set by callers and admins, like
-- the stage. The two money columns get no grant at all, like deal_value_inr (2.8.3): admins read them through
-- v_leads_admin, admin server actions write them with the service role and the engine reads them directly.
-- v_leads_admin and v_pipeline are rebuilt with the new money columns at the end. They are dropped first
-- because the `v.*` in their definitions was fixed when they were created; no other view depends on them.
-- v_leads_caller, v_sheet_leads and v_lead_funnel are unchanged (no money there; the app reads lost_reason
-- from leads, the engine joins leads itself).
--
-- No trigger changes: stage changes are still logged by leads_after_write (0001).

alter table public.leads
  add column if not exists lost_reason text
    constraint leads_lost_reason_known check (lost_reason in
      ('price','no_need_now','chose_other_vendor','no_reply','not_a_fit','wrong_person','other')),
  add column if not exists retainer_monthly_value numeric(12,2)
    constraint leads_retainer_monthly_value_positive check (retainer_monthly_value >= 0),
  add column if not exists deal_currency text not null default 'INR'
    constraint leads_deal_currency_known check (deal_currency in ('INR','USD','AED','GBP','AUD','CAD','SGD'));

-- lost_reason: like stage. The money columns: nothing (see above).
grant select (lost_reason) on public.leads to authenticated;
grant update (lost_reason) on public.leads to authenticated;

-- The same as 0002 plus the new money columns. NOT security_invoker: it runs with its owner's rights so it
-- can read the money columns, and it returns rows only when the person asking is an admin.
drop view if exists public.v_leads_admin;
create view public.v_leads_admin as
select v.*, l.deal_value_inr, l.retainer_monthly_value, l.deal_currency
from public.v_leads_caller v
join public.leads l on l.id = v.id
where public.auth_role() = 'admin';

-- The same plus money, for the engine (service role) only.
drop view if exists public.v_pipeline;
create view public.v_pipeline with (security_invoker = true) as
select v.*, l.deal_value_inr, l.retainer_monthly_value, l.deal_currency
from public.v_leads_caller v
join public.leads l on l.id = v.id;

-- The grants 0003 gave these two views.
revoke all on public.v_leads_admin, public.v_pipeline from anon, authenticated;
grant select on public.v_leads_admin to authenticated;
