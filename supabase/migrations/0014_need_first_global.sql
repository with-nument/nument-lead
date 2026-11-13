-- 0014_need_first_global.sql : need-first leads from global job feeds and startup news (13 Nov 2026)
--
-- The founder wants paying clients in any industry across the English-speaking, high-pay countries (India,
-- UAE, US, UK, Australia, Canada, Singapore). Two new free sources find companies that say in public they
-- need software built:
--   job_feeds     the monthly Hacker News "Who is hiring?" thread (official Algolia API) and remote job
--                 boards with public APIs or RSS (Himalayas, We Work Remotely); builder roles only
--   startup_news  Indian startup news (Inc42 RSS): funding rounds and launches
-- Both are on unless a value is already set. Research grows from 300 to 800 businesses a day and grounded
-- searches from 250 to 400 (founder: 50 to 60 A and B leads a day).

-- source_records.source: keep the list in step with models.SourceName.
alter table public.source_records drop constraint if exists source_records_source_known;
alter table public.source_records add constraint source_records_source_known check (source in
  ('overture','places','art_registry','osm','apna','grounded_search','gdelt','careers_watch','adzuna','practo',
   'maps_reviews','job_feeds','startup_news','legacy','legacy_skip'));

update public.settings
   set value = value
         || case when value ? 'job_feeds' then '{}'::jsonb else '{"job_feeds": true}'::jsonb end
         || case when value ? 'startup_news' then '{}'::jsonb else '{"startup_news": true}'::jsonb end
 where key = 'sources_enabled';

insert into public.settings (key, value) values
  ('job_feeds.posts_per_day', '80'::jsonb),     -- classify calls a day (g_lite, about 0.05 rupees each)
  ('startup_news.articles_per_day', '40'::jsonb)
on conflict (key) do nothing;

-- Founder, 13 Nov 2026: 50 to 60 A and B leads a day.
insert into public.settings (key, value) values ('research_per_day', '800'::jsonb)
on conflict (key) do update set value = '800'::jsonb
 where (public.settings.value #>> '{}')::int < 800;
insert into public.settings (key, value) values ('grounded_search.per_day', '400'::jsonb)
on conflict (key) do update set value = '400'::jsonb
 where (public.settings.value #>> '{}')::int < 400;

insert into public.source_health (source, enabled) values ('job_feeds', true), ('startup_news', true)
on conflict (source) do nothing;
