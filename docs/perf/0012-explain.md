# 0012_read_performance: EXPLAIN before and after

Migration: `supabase/migrations/0012_read_performance.sql`. Not applied by this change.

## How this was measured

The plans could not be read from the live project (PostgREST plan output is off and the app has no SQL
access), so they come from a local Postgres 16 with every migration from 0001 to 0011 applied, small
stand-ins for the Supabase `auth` and `storage` schemas, and synthetic data at a projected size:
60,000 businesses, 24,000 contacts, 15,000 signals, 96,000 facts, 14,000 scores, 6,000 leads,
30,000 activities, 360 Do not contact rows. Every query runs as `authenticated` with an admin's JWT
claims, so Row Level Security applies as it does for the app. `EXPLAIN (ANALYZE, BUFFERS)`, best of
three runs. "Before" is 0001 to 0011, "after" adds 0012.

Live sizes on 12 Nov 2026 for comparison: 27,575 businesses, 754 contacts, 13 signals, 0 leads (fresh
start), so today the gap is small; it grows with every night run.

## Execution time (ms)

| Query (page) | Before | After | Seq scans before | Seq scans after |
|---|---:|---:|---|---|
| today_count_v_today | 1,311.28 | 20.41 | contacts, suppression | suppression |
| today_send_list | 1,291.41 | 22.18 | contacts, suppression | suppression |
| today_followups | 3,491.26 | 69.6 | contacts, suppression | suppression |
| today_count_overdue_leads | 2.49 | 0.78 | none | none |
| today_won_events | 3.37 | 0.79 | none | none |
| leads_page_default | 21,669.65 | 120.79 | leads, signals, contacts, suppression | leads, suppression |
| leads_page_count | 49.33 | 107.05 | leads | leads, suppression |
| leads_page_filtered | 8.39 | 11.66 | none | suppression |
| leads_cities | 42.98 | 6.26 | leads | leads |
| lead_view_row | 1,337.22 | 1.29 | signals, contacts, suppression | suppression |
| lead_deal_values | 0.97 | 1.6 | none | suppression |
| pipeline_board | 40.91 | 86.96 | leads | leads, suppression |
| insights_funnel | 2,815.72 | 23.4 | leads, signals | leads |
| insights_leads | 7,929.1 | 37.74 | leads, signals, contacts, suppression | suppression |
| insights_researched_count | 32.02 | 0.8 | businesses | none |
| engine_researched_yesterday | 216.73 | 5.94 | businesses | none |
| engine_leads_yesterday | 24.3 | 1.56 | leads | leads |
| engine_costs_today | 58.63 | 5.05 | costs | costs |
| lead_evidence_contacts | 25.02 | 1.37 | leads, contacts | leads |
| lead_evidence_facts | 22.45 | 1.34 | leads | leads |

What changed the big ones:

- **RLS filters ran per row and could not be estimated.** Every view row called `auth_role()` (a profiles
  lookup) on leads, businesses, scores, signals and contacts, and the planner guessed those filters keep
  1.5% of rows. It then picked nested loops that re-read the whole sorted contact and signal lists once per
  lead: 106 million rows removed by a join filter for one page of 50 leads. The policies now call
  `(select auth_role())`, worked out once per query.
- **v_leads_caller and v_funnel pick the top signal and best contact with `LATERAL ... LIMIT 1`** (same
  rule and order as `v_top_signal` and `v_primary_contact`), so each returned lead costs two index lookups.
  The lead page row: 1,337 ms to 1.3 ms. Today's send list: 1,291 ms to 22 ms. Leads page: 21.7 s to 121 ms.
- **Do not contact check** is two `NOT EXISTS` (phone, email) instead of one with `OR`, a hash anti join or
  an index probe instead of a nested loop over every suppression row.
- **Indexes**: `businesses (researched_at)` (Engine and Insights counts: 217 ms to 6 ms),
  `leads (created_at desc nulls last, id)`, `leads (last_activity_at desc nulls last, id)`,
  `contacts (business_id)`.

Trade-off, measured: a query that reads every lead through `v_leads_caller` (the Leads page total count,
the Pipeline board with 4,600 open leads) now does two index lookups per lead instead of one hash join
over two sorted lists: 49 ms to 107 ms and 41 ms to 87 ms here. Before, the same queries were fast only
when the planner happened to choose hash joins; the page and lead queries above show what happened when it
did not. The app already counts the KPI tiles from `leads` directly. The remaining sequential scans on
`suppression` are the planner's choice for a 4 page table; the unique phone and email indexes take over as
it grows.

## Queries

```sql
-- today_count_v_today
select count(*) from public.v_today;
-- today_send_list
select lead_id, company, grade, total from public.v_today order by grade, total desc nulls last, created_at limit 100;
-- today_followups
select * from public.v_followups_due order by due_on limit 100;
-- today_count_overdue_leads
select count(*) from public.leads where due_at < current_date and stage not in ('won','retainer','lost','not_now','not_a_fit','wrong_contact');
-- today_won_events
select lead_id, payload from public.activities where type = 'stage_change' and at >= date_trunc('month', now()) limit 2000;
-- leads_page_default
select id, name, grade, stage, total, top_signal_type, phone_e164 from public.v_leads_caller order by created_at desc nulls last, id limit 50;
-- leads_page_count
select count(*) from public.v_leads_caller;
-- leads_page_filtered
select id, name from public.v_leads_caller where segment_id = 'clinics-in' and grade in ('A','B') order by total desc nulls last, id limit 50;
-- leads_cities
select b.city from public.leads l join public.businesses b on b.id = l.business_id where b.city is not null limit 5000;
-- lead_view_row
select * from public.v_leads_caller where id = (select id from public.leads order by id limit 1 offset 77);
-- lead_deal_values
select id, deal_value_inr from public.v_leads_admin where id in (select id from public.leads order by id limit 50);
-- pipeline_board
select id, name, city, grade, stage from public.v_leads_caller where stage <> 'new' order by last_activity_at desc limit 1000;
-- insights_funnel
select * from public.v_funnel where created_on between current_date - 29 and current_date;
-- insights_leads
select id, stage, phone_e164, phone_source, top_signal_at, created_at from public.v_leads_caller where created_at >= now() - interval '30 days' limit 10000;
-- insights_researched_count
select count(*) from public.businesses where researched_at >= now() - interval '30 days' and researched_at < now();
-- engine_researched_yesterday
select segment_id from public.businesses where researched_at >= current_date - 1 and researched_at < current_date limit 5000;
-- engine_leads_yesterday
select segment_id from public.leads where created_at >= current_date - 1 and created_at < current_date limit 5000;
-- engine_costs_today
select inr from public.v_costs_daily where day = current_date;
-- lead_evidence_contacts
select * from public.contacts where business_id = (select business_id from public.leads order by id limit 1 offset 77) order by is_decision_maker desc, created_at limit 50;
-- lead_evidence_facts
select * from public.facts where business_id = (select business_id from public.leads order by id limit 1 offset 77) and verified order by created_at desc limit 300;
```

## Plans

### leads_page_default: Before

```text
Limit (actual rows=50 loops=1)
  ->  Sort (actual rows=50 loops=1)
        Sort Key: l.created_at DESC NULLS LAST, l.id
        Sort Method: top-N heapsort  Memory: 34kB
        ->  Nested Loop Left Join (actual rows=6000 loops=1)
              Join Filter: (c.business_id = l.business_id)
              Rows Removed by Join Filter: 106401178
              ->  Nested Loop Left Join (actual rows=6000 loops=1)
                    Join Filter: (g.business_id = l.business_id)
                    Rows Removed by Join Filter: 75090976
                    ->  Nested Loop Left Join (actual rows=6000 loops=1)
                          ->  Nested Loop (actual rows=6000 loops=1)
                                ->  Seq Scan on leads l (actual rows=6000 loops=1)
                                      Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                                ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=6000)
                                      Index Cond: (id = l.business_id)
                                      Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                          ->  Index Scan using scores_pkey on scores sc (actual rows=1 loops=6000)
                                Index Cond: (id = l.score_id)
                                Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                    ->  Unique (actual rows=12515 loops=6000)
                          ->  Sort (actual rows=12515 loops=6000)
                                Sort Key: g.business_id, g.points DESC, g.observed_at DESC
                                Sort Method: quicksort  Memory: 1543kB
                                ->  Seq Scan on signals g (actual rows=14913 loops=1)
                                      Filter: ((expires_at > now()) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
              ->  Unique (actual rows=17734 loops=6000)
                    ->  Sort (actual rows=17734 loops=6000)
                          Sort Key: c.business_id, ((c.phone_e164 IS NOT NULL)) DESC, c.is_decision_maker DESC, ((c.phone_type = 'mobile'::text)) DESC, c.verified DESC, ((c.source = 'website'::text)) DESC, c.created_at
                          Sort Method: quicksort  Memory: 2617kB
                          ->  Nested Loop Anti Join (actual rows=23667 loops=1)
                                Join Filter: ((su.phone_e164 = c.phone_e164) OR (lower(su.email) = lower(c.email)))
                                Rows Removed by Join Filter: 8507502
                                ->  Seq Scan on contacts c (actual rows=23931 loops=1)
                                      Filter: ((NOT do_not_contact) AND ((phone_e164 IS NOT NULL) OR (email IS NOT NULL)) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
                                ->  Materialize (actual rows=356 loops=23931)
                                      ->  Seq Scan on suppression su (actual rows=358 loops=1)
                                            Filter: (auth_role() = ANY ('{admin,caller}'::text[]))
Planning Time: 6.519 ms
Execution Time: 12935.801 ms
```

### leads_page_default: After

```text
Limit (actual rows=50 loops=1)
  InitPlan 1 (returns $0)
    ->  Result (actual rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result (actual rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result (actual rows=1 loops=1)
  ->  Sort (actual rows=50 loops=1)
        Sort Key: l.created_at DESC NULLS LAST, l.id
        Sort Method: top-N heapsort  Memory: 34kB
        ->  Nested Loop Left Join (actual rows=6000 loops=1)
              ->  Nested Loop Left Join (actual rows=6000 loops=1)
                    ->  Nested Loop Left Join (actual rows=6000 loops=1)
                          ->  Nested Loop (actual rows=6000 loops=1)
                                ->  Seq Scan on leads l (actual rows=6000 loops=1)
                                      Filter: ($0 = ANY ('{admin,caller,viewer}'::text[]))
                                ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=6000)
                                      Index Cond: (id = l.business_id)
                                      Filter: ($1 = ANY ('{admin,caller,viewer}'::text[]))
                          ->  Index Scan using scores_pkey on scores sc (actual rows=1 loops=6000)
                                Index Cond: (id = l.score_id)
                                Filter: ($2 = ANY ('{admin,caller,viewer}'::text[]))
                    ->  Limit (actual rows=0 loops=6000)
                          InitPlan 4 (returns $4)
                            ->  Result (actual rows=1 loops=1)
                          ->  Sort (actual rows=0 loops=6000)
                                Sort Key: g.points DESC, g.observed_at DESC
                                Sort Method: quicksort  Memory: 25kB
                                ->  Index Scan using signals_business_active_idx on signals g (actual rows=0 loops=6000)
                                      Index Cond: ((business_id = l.business_id) AND (expires_at > now()))
                                      Filter: ($4 = ANY ('{admin,caller,viewer}'::text[]))
              ->  Limit (actual rows=0 loops=6000)
                    InitPlan 5 (returns $6)
                      ->  Result (actual rows=1 loops=1)
                    InitPlan 6 (returns $7)
                      ->  Result (actual rows=1 loops=1)
                    InitPlan 7 (returns $8)
                      ->  Result (never executed)
                    ->  Sort (actual rows=0 loops=6000)
                          Sort Key: ((c.phone_e164 IS NOT NULL)) DESC, c.is_decision_maker DESC, ((c.phone_type = 'mobile'::text)) DESC, c.verified DESC, ((c.source = 'website'::text)) DESC, c.created_at
                          Sort Method: quicksort  Memory: 25kB
                          ->  Nested Loop Anti Join (actual rows=0 loops=6000)
                                Join Filter: (lower(su_1.email) = lower(c.email))
                                ->  Nested Loop Anti Join (actual rows=0 loops=6000)
                                      Join Filter: (su.phone_e164 = c.phone_e164)
                                      Rows Removed by Join Filter: 139
                                      ->  Index Scan using contacts_business_idx on contacts c (actual rows=0 loops=6000)
                                            Index Cond: (business_id = l.business_id)
                                            Filter: ((NOT do_not_contact) AND ((phone_e164 IS NOT NULL) OR (email IS NOT NULL)) AND ($6 = ANY ('{admin,caller,viewer}'::text[])))
                                      ->  Seq Scan on suppression su (actual rows=355 loops=2339)
                                            Filter: ($7 = ANY ('{admin,caller}'::text[]))
                                ->  Index Scan using suppression_email_uq on suppression su_1 (actual rows=0 loops=2314)
                                      Filter: ($8 = ANY ('{admin,caller}'::text[]))
Planning Time: 3.607 ms
Execution Time: 108.525 ms
```

### lead_view_row: Before

```text
Merge Left Join (actual rows=1 loops=1)
  Merge Cond: (l.business_id = c.business_id)
  InitPlan 1 (returns $0)
    ->  Limit (actual rows=1 loops=1)
          ->  Index Only Scan using leads_pkey on leads (actual rows=78 loops=1)
                Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                Heap Fetches: 0
  ->  Nested Loop Left Join (actual rows=1 loops=1)
        ->  Nested Loop (actual rows=1 loops=1)
              ->  Merge Left Join (actual rows=1 loops=1)
                    Merge Cond: (l.business_id = g.business_id)
                    ->  Sort (actual rows=1 loops=1)
                          Sort Key: l.business_id
                          Sort Method: quicksort  Memory: 25kB
                          ->  Index Scan using leads_pkey on leads l (actual rows=1 loops=1)
                                Index Cond: (id = $0)
                                Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                    ->  Unique (actual rows=5303 loops=1)
                          ->  Sort (actual rows=5303 loops=1)
                                Sort Key: g.business_id, g.points DESC, g.observed_at DESC
                                Sort Method: quicksort  Memory: 1776kB
                                ->  Seq Scan on signals g (actual rows=14913 loops=1)
                                      Filter: ((expires_at > now()) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
              ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=1)
                    Index Cond: (id = l.business_id)
                    Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
        ->  Index Scan using scores_pkey on scores sc (actual rows=1 loops=1)
              Index Cond: (id = l.score_id)
              Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
  ->  Unique (actual rows=8354 loops=1)
        ->  Sort (actual rows=8354 loops=1)
              Sort Key: c.business_id, ((c.phone_e164 IS NOT NULL)) DESC, c.is_decision_maker DESC, ((c.phone_type = 'mobile'::text)) DESC, c.verified DESC, ((c.source = 'website'::text)) DESC, c.created_at
              Sort Method: quicksort  Memory: 3403kB
              ->  Nested Loop Anti Join (actual rows=23667 loops=1)
                    Join Filter: ((su.phone_e164 = c.phone_e164) OR (lower(su.email) = lower(c.email)))
                    Rows Removed by Join Filter: 8507502
                    ->  Seq Scan on contacts c (actual rows=23931 loops=1)
                          Filter: ((NOT do_not_contact) AND ((phone_e164 IS NOT NULL) OR (email IS NOT NULL)) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
                    ->  Materialize (actual rows=356 loops=23931)
                          ->  Seq Scan on suppression su (actual rows=358 loops=1)
                                Filter: (auth_role() = ANY ('{admin,caller}'::text[]))
Planning Time: 4.513 ms
Execution Time: 1239.601 ms
```

### lead_view_row: After

```text
Nested Loop Left Join (actual rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Limit (actual rows=1 loops=1)
          InitPlan 1 (returns $0)
            ->  Result (actual rows=1 loops=1)
          ->  Sort (actual rows=78 loops=1)
                Sort Key: leads.id
                Sort Method: top-N heapsort  Memory: 28kB
                ->  Index Only Scan using leads_last_activity_idx on leads (actual rows=6000 loops=1)
                      Filter: ($0 = ANY ('{admin,caller,viewer}'::text[]))
                      Heap Fetches: 0
  InitPlan 3 (returns $2)
    ->  Result (actual rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result (actual rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result (actual rows=1 loops=1)
  ->  Nested Loop Left Join (actual rows=1 loops=1)
        ->  Nested Loop Left Join (actual rows=1 loops=1)
              ->  Nested Loop (actual rows=1 loops=1)
                    ->  Index Scan using leads_pkey on leads l (actual rows=1 loops=1)
                          Index Cond: (id = $1)
                          Filter: ($2 = ANY ('{admin,caller,viewer}'::text[]))
                    ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=1)
                          Index Cond: (id = l.business_id)
                          Filter: ($3 = ANY ('{admin,caller,viewer}'::text[]))
              ->  Index Scan using scores_pkey on scores sc (actual rows=1 loops=1)
                    Index Cond: (id = l.score_id)
                    Filter: ($4 = ANY ('{admin,caller,viewer}'::text[]))
        ->  Limit (actual rows=1 loops=1)
              InitPlan 6 (returns $6)
                ->  Result (actual rows=1 loops=1)
              ->  Sort (actual rows=1 loops=1)
                    Sort Key: g.points DESC, g.observed_at DESC
                    Sort Method: quicksort  Memory: 25kB
                    ->  Index Scan using signals_business_active_idx on signals g (actual rows=1 loops=1)
                          Index Cond: ((business_id = l.business_id) AND (expires_at > now()))
                          Filter: ($6 = ANY ('{admin,caller,viewer}'::text[]))
  ->  Limit (actual rows=1 loops=1)
        InitPlan 7 (returns $8)
          ->  Result (actual rows=1 loops=1)
        InitPlan 8 (returns $9)
          ->  Result (actual rows=1 loops=1)
        InitPlan 9 (returns $10)
          ->  Result (never executed)
        ->  Sort (actual rows=1 loops=1)
              Sort Key: ((c.phone_e164 IS NOT NULL)) DESC, c.is_decision_maker DESC, ((c.phone_type = 'mobile'::text)) DESC, c.verified DESC, ((c.source = 'website'::text)) DESC, c.created_at
              Sort Method: quicksort  Memory: 25kB
              ->  Nested Loop Anti Join (actual rows=1 loops=1)
                    Join Filter: (lower(su_1.email) = lower(c.email))
                    ->  Nested Loop Anti Join (actual rows=1 loops=1)
                          Join Filter: (su.phone_e164 = c.phone_e164)
                          Rows Removed by Join Filter: 358
                          ->  Index Scan using contacts_business_idx on contacts c (actual rows=1 loops=1)
                                Index Cond: (business_id = l.business_id)
                                Filter: ((NOT do_not_contact) AND ((phone_e164 IS NOT NULL) OR (email IS NOT NULL)) AND ($8 = ANY ('{admin,caller,viewer}'::text[])))
                          ->  Seq Scan on suppression su (actual rows=358 loops=1)
                                Filter: ($9 = ANY ('{admin,caller}'::text[]))
                    ->  Index Scan using suppression_email_uq on suppression su_1 (actual rows=0 loops=1)
                          Filter: ($10 = ANY ('{admin,caller}'::text[]))
Planning Time: 3.880 ms
Execution Time: 1.815 ms
```

### today_send_list: Before

```text
Limit (actual rows=100 loops=1)
  ->  Subquery Scan on v_today (actual rows=100 loops=1)
        ->  Sort (actual rows=100 loops=1)
              Sort Key: l.grade, sc.total DESC NULLS LAST, l.created_at
              Sort Method: top-N heapsort  Memory: 47kB
              ->  Nested Loop Anti Join (actual rows=248 loops=1)
                    ->  Hash Left Join (actual rows=248 loops=1)
                          Hash Cond: (l.business_id = pc.business_id)
                          Filter: ((pc.phone_e164 IS NOT NULL) OR (l.channel <> 'whatsapp'::text))
                          Rows Removed by Filter: 428
                          ->  Nested Loop Left Join (actual rows=676 loops=1)
                                ->  Nested Loop (actual rows=676 loops=1)
                                      ->  Bitmap Heap Scan on leads l (actual rows=676 loops=1)
                                            Recheck Cond: ((stage = 'new'::text) AND (grade = ANY ('{A,B}'::bpchar[])))
                                            Filter: (((skipped_until IS NULL) OR (skipped_until <= now())) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
                                            Heap Blocks: exact=143
                                            ->  BitmapAnd (actual rows=0 loops=1)
                                                  ->  Bitmap Index Scan on leads_stage_idx (actual rows=1399 loops=1)
                                                        Index Cond: (stage = 'new'::text)
                                                  ->  Bitmap Index Scan on leads_segment_grade_idx (actual rows=2937 loops=1)
                                                        Index Cond: (grade = ANY ('{A,B}'::bpchar[]))
                                      ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=676)
                                            Index Cond: (id = l.business_id)
                                            Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                                ->  Index Scan using scores_pkey on scores sc (actual rows=1 loops=676)
                                      Index Cond: (id = l.score_id)
                                      Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                          ->  Hash (actual rows=23667 loops=1)
                                Buckets: 32768 (originally 1024)  Batches: 1 (originally 1)  Memory Usage: 1689kB
                                ->  Subquery Scan on pc (actual rows=23667 loops=1)
                                      ->  Unique (actual rows=23667 loops=1)
                                            ->  Sort (actual rows=23667 loops=1)
                                                  Sort Key: c.business_id, ((c.phone_e164 IS NOT NULL)) DESC, c.is_decision_maker DESC, ((c.phone_type = 'mobile'::text)) DESC, c.verified DESC, ((c.source = 'website'::text)) DESC, c.created_at
                                                  Sort Method: quicksort  Memory: 2617kB
                                                  ->  Nested Loop Anti Join (actual rows=23667 loops=1)
                                                        Join Filter: ((su_1.phone_e164 = c.phone_e164) OR (lower(su_1.email) = lower(c.email)))
                                                        Rows Removed by Join Filter: 8507502
                                                        ->  Seq Scan on contacts c (actual rows=23931 loops=1)
                                                              Filter: ((NOT do_not_contact) AND ((phone_e164 IS NOT NULL) OR (email IS NOT NULL)) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
                                                        ->  Materialize (actual rows=356 loops=23931)
                                                              ->  Seq Scan on suppression su_1 (actual rows=358 loops=1)
                                                                    Filter: (auth_role() = ANY ('{admin,caller}'::text[]))
                    ->  Index Only Scan using suppression_domain_uq on suppression su (actual rows=0 loops=248)
                          Index Cond: (web_domain = b.web_domain)
                          Filter: (auth_role() = ANY ('{admin,caller}'::text[]))
                          Heap Fetches: 0
Planning Time: 11.053 ms
Execution Time: 1447.311 ms
```

### today_send_list: After

```text
Limit (actual rows=100 loops=1)
  ->  Subquery Scan on v_today (actual rows=100 loops=1)
        ->  Sort (actual rows=100 loops=1)
              Sort Key: l.grade, sc.total DESC NULLS LAST, l.created_at
              Sort Method: top-N heapsort  Memory: 47kB
              InitPlan 1 (returns $0)
                ->  Result (never executed)
              InitPlan 2 (returns $1)
                ->  Result (actual rows=1 loops=1)
              InitPlan 3 (returns $2)
                ->  Result (actual rows=1 loops=1)
              InitPlan 4 (returns $3)
                ->  Result (actual rows=1 loops=1)
              ->  Nested Loop Anti Join (actual rows=248 loops=1)
                    ->  Nested Loop Left Join (actual rows=248 loops=1)
                          Filter: ((c.phone_e164 IS NOT NULL) OR (l.channel <> 'whatsapp'::text))
                          Rows Removed by Filter: 428
                          ->  Nested Loop Left Join (actual rows=676 loops=1)
                                ->  Nested Loop Left Join (actual rows=676 loops=1)
                                      ->  Nested Loop (actual rows=676 loops=1)
                                            ->  Bitmap Heap Scan on leads l (actual rows=676 loops=1)
                                                  Recheck Cond: (stage = 'new'::text)
                                                  Filter: ((grade = ANY ('{A,B}'::bpchar[])) AND ($1 = ANY ('{admin,caller,viewer}'::text[])) AND ((skipped_until IS NULL) OR (skipped_until <= now())))
                                                  Rows Removed by Filter: 723
                                                  Heap Blocks: exact=144
                                                  ->  Bitmap Index Scan on leads_stage_idx (actual rows=1399 loops=1)
                                                        Index Cond: (stage = 'new'::text)
                                            ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=676)
                                                  Index Cond: (id = l.business_id)
                                                  Filter: ($2 = ANY ('{admin,caller,viewer}'::text[]))
                                      ->  Index Scan using scores_pkey on scores sc (actual rows=1 loops=676)
                                            Index Cond: (id = l.score_id)
                                            Filter: ($3 = ANY ('{admin,caller,viewer}'::text[]))
                                ->  Limit (actual rows=0 loops=676)
                                      InitPlan 5 (returns $5)
                                        ->  Result (actual rows=1 loops=1)
                                      ->  Sort (actual rows=0 loops=676)
                                            Sort Key: g.points DESC, g.observed_at DESC
                                            Sort Method: quicksort  Memory: 25kB
                                            ->  Index Scan using signals_business_active_idx on signals g (actual rows=0 loops=676)
                                                  Index Cond: ((business_id = l.business_id) AND (expires_at > now()))
                                                  Filter: ($5 = ANY ('{admin,caller,viewer}'::text[]))
                          ->  Limit (actual rows=0 loops=676)
                                InitPlan 6 (returns $7)
                                  ->  Result (actual rows=1 loops=1)
                                InitPlan 7 (returns $8)
                                  ->  Result (actual rows=1 loops=1)
                                InitPlan 8 (returns $9)
                                  ->  Result (never executed)
                                ->  Sort (actual rows=0 loops=676)
                                      Sort Key: ((c.phone_e164 IS NOT NULL)) DESC, c.is_decision_maker DESC, ((c.phone_type = 'mobile'::text)) DESC, c.verified DESC, ((c.source = 'website'::text)) DESC, c.created_at
                                      Sort Method: quicksort  Memory: 25kB
                                      ->  Nested Loop Anti Join (actual rows=0 loops=676)
                                            Join Filter: (lower(su_2.email) = lower(c.email))
                                            ->  Nested Loop Anti Join (actual rows=0 loops=676)
                                                  Join Filter: (su_1.phone_e164 = c.phone_e164)
                                                  Rows Removed by Join Filter: 132
                                                  ->  Index Scan using contacts_business_idx on contacts c (actual rows=0 loops=676)
                                                        Index Cond: (business_id = l.business_id)
                                                        Filter: ((NOT do_not_contact) AND ((phone_e164 IS NOT NULL) OR (email IS NOT NULL)) AND ($7 = ANY ('{admin,caller,viewer}'::text[])))
                                                  ->  Seq Scan on suppression su_1 (actual rows=352 loops=254)
                                                        Filter: ($8 = ANY ('{admin,caller}'::text[]))
                                            ->  Index Scan using suppression_email_uq on suppression su_2 (actual rows=0 loops=248)
                                                  Filter: ($9 = ANY ('{admin,caller}'::text[]))
                    ->  Index Only Scan using suppression_domain_uq on suppression su (actual rows=0 loops=248)
                          Index Cond: (web_domain = b.web_domain)
                          Filter: ($0 = ANY ('{admin,caller}'::text[]))
                          Heap Fetches: 0
Planning Time: 2.384 ms
Execution Time: 24.034 ms
```

### insights_funnel: Before

```text
Nested Loop Left Join (actual rows=1944 loops=1)
  Join Filter: (g.business_id = l.business_id)
  Rows Removed by Join Filter: 24472579
  CTE ranks
    ->  Values Scan on "*VALUES*" (actual rows=8 loops=1)
  ->  Nested Loop (actual rows=1944 loops=1)
        ->  Nested Loop (actual rows=1944 loops=1)
              ->  GroupAggregate (actual rows=6000 loops=1)
                    Group Key: l_1.id
                    ->  Sort (actual rows=6873 loops=1)
                          Sort Key: l_1.id
                          Sort Method: quicksort  Memory: 509kB
                          ->  Hash Left Join (actual rows=6873 loops=1)
                                Hash Cond: (l_1.stage = r_now.stage)
                                ->  Hash Left Join (actual rows=6873 loops=1)
                                      Hash Cond: (l_1.id = a.lead_id)
                                      ->  Seq Scan on leads l_1 (actual rows=6000 loops=1)
                                            Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                                      ->  Hash (actual rows=3958 loops=1)
                                            Buckets: 4096 (originally 1024)  Batches: 1 (originally 1)  Memory Usage: 233kB
                                            ->  Hash Left Join (actual rows=3958 loops=1)
                                                  Hash Cond: ((a.payload ->> 'to'::text) = r_hist.stage)
                                                  ->  Bitmap Heap Scan on activities a (actual rows=3958 loops=1)
                                                        Recheck Cond: (type = 'stage_change'::text)
                                                        Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
                                                        Heap Blocks: exact=371
                                                        ->  Bitmap Index Scan on activities_type_time_idx (actual rows=3958 loops=1)
                                                              Index Cond: (type = 'stage_change'::text)
                                                  ->  Hash (actual rows=8 loops=1)
                                                        Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                                        ->  CTE Scan on ranks r_hist (actual rows=8 loops=1)
                                ->  Hash (actual rows=8 loops=1)
                                      Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                      ->  CTE Scan on ranks r_now (actual rows=8 loops=1)
              ->  Memoize (actual rows=0 loops=6000)
                    Cache Key: l_1.id
                    Cache Mode: logical
                    Hits: 0  Misses: 6000  Evictions: 0  Overflows: 0  Memory Usage: 706kB
                    ->  Index Scan using leads_pkey on leads l (actual rows=0 loops=6000)
                          Index Cond: (id = l_1.id)
                          Filter: ((auth_role() = ANY ('{admin,caller,viewer}'::text[])) AND (((created_at AT TIME ZONE 'Asia/Kolkata'::text))::date <= CURRENT_DATE) AND (((created_at AT TIME ZONE 'Asia/Kolkata'::text))::date >= (CURRENT_DATE - 29)))
                          Rows Removed by Filter: 1
        ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=1944)
              Index Cond: (id = l.business_id)
              Filter: (auth_role() = ANY ('{admin,caller,viewer}'::text[]))
  ->  Unique (actual rows=12589 loops=1944)
        ->  Sort (actual rows=12589 loops=1944)
              Sort Key: g.business_id, g.points DESC, g.observed_at DESC
              Sort Method: quicksort  Memory: 1543kB
              ->  Seq Scan on signals g (actual rows=14913 loops=1)
                    Filter: ((expires_at > now()) AND (auth_role() = ANY ('{admin,caller,viewer}'::text[])))
Planning Time: 2.505 ms
Execution Time: 1594.348 ms
```

### insights_funnel: After

```text
Nested Loop Left Join (actual rows=1944 loops=1)
  CTE ranks
    ->  Values Scan on "*VALUES*" (actual rows=8 loops=1)
  InitPlan 2 (returns $1)
    ->  Result (actual rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result (actual rows=1 loops=1)
  ->  Nested Loop (actual rows=1944 loops=1)
        ->  Nested Loop (actual rows=1944 loops=1)
              ->  GroupAggregate (actual rows=6000 loops=1)
                    Group Key: l_1.id
                    InitPlan 4 (returns $3)
                      ->  Result (actual rows=1 loops=1)
                    InitPlan 5 (returns $4)
                      ->  Result (actual rows=1 loops=1)
                    ->  Sort (actual rows=6873 loops=1)
                          Sort Key: l_1.id
                          Sort Method: quicksort  Memory: 509kB
                          ->  Hash Left Join (actual rows=6873 loops=1)
                                Hash Cond: (l_1.stage = r_now.stage)
                                ->  Hash Right Join (actual rows=6873 loops=1)
                                      Hash Cond: (a.lead_id = l_1.id)
                                      ->  Hash Left Join (actual rows=3958 loops=1)
                                            Hash Cond: ((a.payload ->> 'to'::text) = r_hist.stage)
                                            ->  Bitmap Heap Scan on activities a (actual rows=3958 loops=1)
                                                  Recheck Cond: (type = 'stage_change'::text)
                                                  Filter: ($4 = ANY ('{admin,caller,viewer}'::text[]))
                                                  Heap Blocks: exact=371
                                                  ->  Bitmap Index Scan on activities_type_time_idx (actual rows=3958 loops=1)
                                                        Index Cond: (type = 'stage_change'::text)
                                            ->  Hash (actual rows=8 loops=1)
                                                  Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                                  ->  CTE Scan on ranks r_hist (actual rows=8 loops=1)
                                      ->  Hash (actual rows=6000 loops=1)
                                            Buckets: 8192 (originally 1024)  Batches: 1 (originally 1)  Memory Usage: 395kB
                                            ->  Seq Scan on leads l_1 (actual rows=6000 loops=1)
                                                  Filter: ($3 = ANY ('{admin,caller,viewer}'::text[]))
                                ->  Hash (actual rows=8 loops=1)
                                      Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                      ->  CTE Scan on ranks r_now (actual rows=8 loops=1)
              ->  Memoize (actual rows=0 loops=6000)
                    Cache Key: l_1.id
                    Cache Mode: logical
                    Hits: 0  Misses: 6000  Evictions: 0  Overflows: 0  Memory Usage: 706kB
                    ->  Index Scan using leads_pkey on leads l (actual rows=0 loops=6000)
                          Index Cond: (id = l_1.id)
                          Filter: (($1 = ANY ('{admin,caller,viewer}'::text[])) AND (((created_at AT TIME ZONE 'Asia/Kolkata'::text))::date <= CURRENT_DATE) AND (((created_at AT TIME ZONE 'Asia/Kolkata'::text))::date >= (CURRENT_DATE - 29)))
                          Rows Removed by Filter: 1
        ->  Index Scan using businesses_pkey on businesses b (actual rows=1 loops=1944)
              Index Cond: (id = l.business_id)
              Filter: ($2 = ANY ('{admin,caller,viewer}'::text[]))
  ->  Limit (actual rows=0 loops=1944)
        InitPlan 6 (returns $6)
          ->  Result (actual rows=1 loops=1)
        ->  Sort (actual rows=0 loops=1944)
              Sort Key: g.points DESC, g.observed_at DESC
              Sort Method: quicksort  Memory: 25kB
              ->  Index Scan using signals_business_active_idx on signals g (actual rows=0 loops=1944)
                    Index Cond: ((business_id = l.business_id) AND (expires_at > now()))
                    Filter: ($6 = ANY ('{admin,caller,viewer}'::text[]))
Planning Time: 2.429 ms
Execution Time: 23.387 ms
```

### engine_researched_yesterday: Before

```text
Limit (actual rows=0 loops=1)
  ->  Seq Scan on businesses (actual rows=0 loops=1)
        Filter: ((auth_role() = ANY ('{admin,caller,viewer}'::text[])) AND (researched_at < CURRENT_DATE) AND (researched_at >= (CURRENT_DATE - 1)))
        Rows Removed by Filter: 60000
Planning Time: 0.765 ms
Execution Time: 213.691 ms
```

### engine_researched_yesterday: After

```text
Limit (actual rows=0 loops=1)
  InitPlan 1 (returns $0)
    ->  Result (actual rows=1 loops=1)
  ->  Bitmap Heap Scan on businesses (actual rows=0 loops=1)
        Recheck Cond: (researched_at IS NOT NULL)
        Filter: (($0 = ANY ('{admin,caller,viewer}'::text[])) AND (researched_at < CURRENT_DATE) AND (researched_at >= (CURRENT_DATE - 1)))
        Rows Removed by Filter: 20000
        Heap Blocks: exact=1424
        ->  Bitmap Index Scan on businesses_researched_idx (actual rows=20000 loops=1)
Planning Time: 0.497 ms
Execution Time: 6.308 ms
```

