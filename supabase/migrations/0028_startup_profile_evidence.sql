-- 0028_startup_profile_evidence.sql : the evidence behind every startup profile answer (15 Nov 2026, lane E2b)
--
-- startup_profiles (0020) keeps evidence ids for the team size, the tech team and can-pay only. The other answers
-- (is_startup, product_status, no_code_platform, uses_ai, the funding columns, domain_created_at) had nowhere to
-- keep theirs, so they could not be traced back to a fact or a signal. `evidence` holds, for every answer, the
-- fact and signal ids it rests on and one plain line saying why (pipeline/qualify.py writes it):
--   {"tech_team": {"ids": ["<fact id>", "<signal id>"], "why": "no tech team: ..."}, "funding": {...}, ...}
-- The table keeps its row level security and its select grant; a new column needs neither.

alter table public.startup_profiles
  add column if not exists evidence jsonb not null default '{}'::jsonb;

comment on column public.startup_profiles.evidence is
  'Per answer: {"ids": [fact or signal ids], "why": "one plain line"}, written by pipeline/qualify.py';
