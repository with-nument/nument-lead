-- 0004_seed.sql : defaults. Safe to re-run (only inserts missing rows).

insert into public.settings (key, value) values
  -- A.12.1
  ('daily_cap_inr',                  '750'::jsonb),
  ('alert_pct',                      '80'::jsonb),
  ('research_per_day',               '300'::jsonb),
  ('fx_inr_per_usd',                 '88'::jsonb),
  ('tier',                           '"balanced"'::jsonb),
  ('sheet_sync_enabled',             'true'::jsonb),
  ('providers_enabled',              '{"gemini": true, "openai": false}'::jsonb),
  ('sources_enabled',                '{"overture": true, "places": true, "art_registry": true, "osm": true,
                                       "apna": true, "grounded_search": true, "gdelt": true,
                                       "careers_watch": true, "adzuna": false, "practo": false}'::jsonb),
  ('segments_enabled',               '{"clinics-in": true, "realestate-in": true, "education-in": true,
                                       "clinics-ae": true, "realestate-ae": true, "education-ae": true}'::jsonb),
  -- per-source and per-task daily caps (Steps 5, 7, 9)
  ('careers_watch.pages_per_day',    '500'::jsonb),
  ('grounded_search.per_day',        '160'::jsonb),
  ('gdelt.queries_per_day',          '30'::jsonb),
  ('ai.classify_per_day',            '1500'::jsonb),
  ('research.browser_pages_per_run', '40'::jsonb),
  ('practo.pages_per_day',           '150'::jsonb),
  ('places_details_cap_in',          '230'::jsonb),
  ('places_details_cap_global',      '30'::jsonb),
  -- queue priority bonus per segment (Step 8.7; Step 16 may change it)
  ('segment_weights',                '{"clinics-in": 0, "realestate-in": 0, "education-in": 0,
                                       "clinics-ae": 0, "realestate-ae": 0, "education-ae": 0}'::jsonb),
  -- state kept by later steps (seeded so plain updates work)
  ('overture_release',               'null'::jsonb),
  ('sheet_state',                    '{"master": {"state": "ok"}, "caller": {"state": "ok"}}'::jsonb),
  ('budget_alert_day',               'null'::jsonb),
  ('score_weights',                  '{}'::jsonb),
  ('score_weights_frozen',           'false'::jsonb)
on conflict (key) do nothing;

insert into public.segments (id, domain, country, display_name, enabled, daily_quota) values
  ('clinics-in',    'clinics',    'in', 'Clinics, India',     true, 80),
  ('realestate-in', 'realestate', 'in', 'Real estate, India', true, 60),
  ('education-in',  'education',  'in', 'Education, India',   true, 50),
  ('clinics-ae',    'clinics',    'ae', 'Clinics, UAE',       true, 40),
  ('realestate-ae', 'realestate', 'ae', 'Real estate, UAE',   true, 40),
  ('education-ae',  'education',  'ae', 'Education, UAE',     true, 30)
on conflict (id) do nothing;
-- Quotas add up to 300 = research_per_day. The engine copies each YAML into segments.config (Step 3.2).

insert into public.source_health (source, enabled) values
  ('overture', true), ('places', true), ('art_registry', true), ('osm', true), ('apna', true),
  ('grounded_search', true), ('gdelt', true), ('careers_watch', true), ('adzuna', false),
  ('practo', false), ('llm:gemini', true), ('llm:openai', false)
on conflict (source) do nothing;
