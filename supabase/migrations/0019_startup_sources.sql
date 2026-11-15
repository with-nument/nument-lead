-- 0019_startup_sources.sql : the startup engine's sources (founder reset, 15 Nov 2026)
--
-- The engine now looks only for startups of 2 to 10 people with no tech team, worldwide. New sources, all free
-- and public:
--   funding_rss    startup funding news feeds (TechCrunch, EU-Startups, Inc42, e27, BetaKit, Startup Daily,
--                  YourStory, TechCabal, Disrupt Africa, LatamList, Tech Funding News, Crunchbase News,
--                  AlleyWatch, Silicon Republic)
--   hn_launches    Hacker News "Show HN" and "Launch HN" (official Algolia API)
--   betalist       pre-launch startups (BetaList feed)
--   sec_edgar      US SEC Form D and Form C filings (small raises, crowdfunding)
--   ats_jobs       public job-board APIs (Greenhouse, Lever, Ashby, Workable): founding-engineer and CTO roles
--   startup_lists  accelerator datasets (yc-oss and similar), filtered to 10 people or fewer
-- A new signal type `launch` (growth, 30 days) records a fresh product launch.

alter table public.source_records drop constraint if exists source_records_source_known;
alter table public.source_records add constraint source_records_source_known check (source in
  ('overture','places','art_registry','osm','apna','grounded_search','gdelt','careers_watch','adzuna','practo',
   'maps_reviews','job_feeds','startup_news','funding_rss','hn_launches','betalist','sec_edgar','ats_jobs',
   'startup_lists','legacy','legacy_skip'));

alter table public.signals drop constraint if exists signals_type_check;
alter table public.signals add constraint signals_type_check check (type in
  ('public_ask','tender','hiring_builder','hiring_frontdesk','review_pain','ads_running','no_booking','slow_site',
   'new_place','new_branch','news','funding','launch'));

update public.settings
   set value = value
         || case when value ? 'funding_rss' then '{}'::jsonb else '{"funding_rss": true}'::jsonb end
         || case when value ? 'hn_launches' then '{}'::jsonb else '{"hn_launches": true}'::jsonb end
         || case when value ? 'betalist' then '{}'::jsonb else '{"betalist": true}'::jsonb end
         || case when value ? 'sec_edgar' then '{}'::jsonb else '{"sec_edgar": true}'::jsonb end
         || case when value ? 'ats_jobs' then '{}'::jsonb else '{"ats_jobs": true}'::jsonb end
         || case when value ? 'startup_lists' then '{}'::jsonb else '{"startup_lists": true}'::jsonb end
 where key = 'sources_enabled';

insert into public.source_health (source, enabled) values
  ('funding_rss', true), ('hn_launches', true), ('betalist', true), ('sec_edgar', true), ('ats_jobs', true),
  ('startup_lists', true)
on conflict (source) do nothing;

-- Grounded search (5,000 free queries a month) shared out per use, about 145 a day in all.
insert into public.settings (key, value) values
  ('grounding.asks_per_day', '60'::jsonb),
  ('grounding.lookup_per_day', '40'::jsonb),
  ('grounding.people_per_day', '30'::jsonb),
  ('grounding.email_snippets_per_day', '15'::jsonb),
  ('funding_rss.items_per_day', '120'::jsonb),
  ('sec_edgar.filings_per_day', '60'::jsonb),
  ('startup.max_team', '10'::jsonb),
  ('startup.max_raise_usd', '2000000'::jsonb)
on conflict (key) do nothing;
