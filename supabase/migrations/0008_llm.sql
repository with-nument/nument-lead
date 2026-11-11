-- 0008_llm.sql : storage for the AI router (Step 4.10.1 and 4.11)
--
-- 0001_core.sql already creates all of this (A.13.5 rule 3), so on a database built from these
-- migrations every statement below is a no-op. It stays so the numbering in A.13.3 holds and a database
-- built from an older 0001 still ends up with the same objects.

-- AI answer cache. db.cache_get(key) returns a row only if expires_at > now().
create table if not exists public.llm_cache (
  key text primary key,
  task text not null,
  model text not null,
  response jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index if not exists llm_cache_expires_idx on public.llm_cache (expires_at);

-- Which provider was planned when a fallback answered, for example 'openai:gpt-5-mini'.
alter table public.costs add column if not exists fallback_from text;

-- Money held for a submitted batch until its results are collected.
create table if not exists public.llm_batch_reservations (
  id bigserial primary key,
  llm_batch_id uuid references public.llm_batches(id) on delete cascade,
  reserved_inr numeric not null,
  released boolean not null default false,
  created_at timestamptz not null default now()
);

-- Engine only: RLS on with no policies.
alter table public.llm_cache enable row level security;
alter table public.llm_batch_reservations enable row level security;

-- Provider switches (Engine page). OpenAI starts off everywhere (A.13.5 rule 5).
insert into public.settings (key, value) values
  ('providers_enabled', '{"gemini": true, "openai": false}'::jsonb)
on conflict (key) do nothing;
