import 'server-only'
import { cacheLife, cacheTag } from 'next/cache'
import { TAGS } from '@/lib/cache-tags'
import { createAdminClient } from '@/lib/supabase/admin'
import { createClient } from '@/lib/supabase/server'
import { getSegments } from './shared'
import { addDays, istDate, istMidnightUtc } from '@/lib/dates'

export const BUDGET_KEYS = ['daily_cap_inr', 'alert_pct', 'research_per_day'] as const
export type BudgetKey = (typeof BUDGET_KEYS)[number]

export type Budget = Record<BudgetKey, number>

/**
 * The budget keys (daily cap, alert share, research per day). Admin only: the Engine and Insights pages
 * check the role before calling, so this reads with the service role and caches for every admin.
 * The budget form updates the tag.
 */
export async function getBudget(): Promise<Budget> {
  'use cache'
  cacheLife('hours')
  cacheTag(TAGS.budget)
  const { data, error } = await createAdminClient().from('settings').select('key, value').in('key', [...BUDGET_KEYS])
  if (error) throw error
  const setting = (key: BudgetKey, fallback: number) => {
    const v = Number(data?.find((s) => s.key === key)?.value)
    return Number.isFinite(v) ? v : fallback
  }
  return {
    daily_cap_inr: setting('daily_cap_inr', 750),
    alert_pct: setting('alert_pct', 80),
    research_per_day: setting('research_per_day', 300),
  }
}

/**
 * The live part of the Engine page: source health, runs, the custom search queue, today's spend and
 * yesterday's numbers per segment. Runs as the signed-in user, so Row Level Security returns nothing to
 * anyone but an admin; the page can start it while the role check runs.
 */
export async function getEngineLive() {
  const sb = await createClient()
  const today = istDate()
  const yesterday = addDays(today, -1)
  const [sources, runs, queries, spend, researched, created] = await Promise.all([
    sb
      .from('v_source_health')
      .select('source, enabled, last_ok_at, last_error_at, last_error, blocked_until, requests_today, health')
      .order('source'),
    sb.from('runs').select('id, kind, started_at, finished_at, status, stats, error').order('started_at', { ascending: false }).limit(20),
    sb.from('custom_queries').select('id, segment_id, query, status, created_at').order('created_at', { ascending: false }).limit(50),
    sb.from('v_costs_daily').select('inr').eq('day', today),
    sb
      .from('businesses')
      .select('segment_id')
      .gte('researched_at', istMidnightUtc(yesterday))
      .lt('researched_at', istMidnightUtc(today))
      .limit(5000),
    // Straight from leads: the same rows as v_leads_caller (every lead has its business), without the
    // view's contact and signal joins.
    sb
      .from('leads')
      .select('segment_id')
      .gte('created_at', istMidnightUtc(yesterday))
      .lt('created_at', istMidnightUtc(today))
      .limit(5000),
  ])
  for (const r of [sources, runs, queries]) if (r.error) throw r.error

  const count = (rows: { segment_id: string | null }[] | null) => {
    const m = new Map<string, number>()
    for (const r of rows ?? []) if (r.segment_id) m.set(r.segment_id, (m.get(r.segment_id) ?? 0) + 1)
    return m
  }
  return {
    researchedBy: count(researched.data),
    leadsBy: count(created.data),
    spendToday: (spend.data ?? []).reduce((sum, r) => sum + Number(r.inr ?? 0), 0),
    sources: sources.data ?? [],
    runs: runs.data ?? [],
    queries: queries.data ?? [],
  }
}

/** Everything the Engine page shows. Admin only: call after the role check (the cached parts use the service role). */
export async function getEngineOverview(live: Promise<Awaited<ReturnType<typeof getEngineLive>>>) {
  const [segments, budget, data] = await Promise.all([getSegments(), getBudget(), live])
  return {
    segments: segments.map((s) => ({
      ...s,
      researchedYesterday: data.researchedBy.get(s.id) ?? 0,
      leadsYesterday: data.leadsBy.get(s.id) ?? 0,
    })),
    budget,
    spendToday: data.spendToday,
    sources: data.sources,
    runs: data.runs,
    queries: data.queries,
  }
}
