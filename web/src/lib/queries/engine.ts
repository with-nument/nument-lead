import 'server-only'
import { cacheLife, cacheTag } from 'next/cache'
import { TAGS } from '@/lib/cache-tags'
import { createAdminClient } from '@/lib/supabase/admin'
import { createClient } from '@/lib/supabase/server'
import { getSegments } from './shared'
import { toEngineLive, type EngineLive } from './page-data'

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
 * The live part of the Engine page in one database call (engine_counts, migration 0024): source health, the
 * last runs, the custom search queue, today's spend and yesterday's numbers per segment, counted in the
 * database. Runs as the signed-in user, so Row Level Security returns nothing to anyone but an admin; the page
 * can start it while the role check runs.
 */
export async function getEngineLive(): Promise<EngineLive> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('engine_counts')
  if (error) throw error
  return toEngineLive(data)
}

/** Everything the Engine page shows. Admin only: call after the role check (the cached parts use the service role). */
export async function getEngineOverview(live: Promise<EngineLive>) {
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
