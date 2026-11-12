-- 0010_review_sources.sql : Practo on, and the new Google Maps reviews source (founder approved, 12 Nov 2026)
--
-- Without a Google Cloud billing account there is no Places data, so clinics rarely had review numbers or
-- review pain. Practo (clinic profiles, India) is switched on at its documented pace: one request every
-- 5 seconds, at most practo.pages_per_day pages a day. maps_reviews reads public Google Maps listings with
-- the research Chromium, one lookup at a time, at most maps_reviews.lookups_per_day lookups and
-- maps_reviews.minutes_per_run minutes a night (about 40 lookups in 4 minutes). It stops on any block,
-- consent wall, CAPTCHA or sign-in prompt.

-- source_records.source: keep the list in step with models.SourceName.
alter table public.source_records drop constraint if exists source_records_source_known;
alter table public.source_records add constraint source_records_source_known check (source in
  ('overture','places','art_registry','osm','apna','grounded_search','gdelt','careers_watch','adzuna','practo',
   'maps_reviews','legacy','legacy_skip'));

-- Practo on (the founder's decision), maps_reviews on unless a value is already set.
update public.settings
   set value = value || '{"practo": true}'::jsonb
         || case when value ? 'maps_reviews' then '{}'::jsonb else '{"maps_reviews": true}'::jsonb end
 where key = 'sources_enabled';

insert into public.settings (key, value) values
  ('maps_reviews.lookups_per_day', '100'::jsonb),
  ('maps_reviews.minutes_per_run', '4'::jsonb)    -- keeps the night job inside the Actions minutes (14.6)
on conflict (key) do nothing;

insert into public.source_health (source, enabled) values ('maps_reviews', true)
on conflict (source) do nothing;
update public.source_health set enabled = true where source = 'practo';
