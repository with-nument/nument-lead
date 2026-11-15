import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { addDays, istDate, istMidnightUtc } from '@/lib/dates'
import { toInsights, type Insights } from './page-data'

export type { CostDay, Counts, CountsRow, Insights, InsightsCosts, InsightsQuality } from './page-data'

// Funnel numbers follow v_funnel (the furthest stage each lead ever reached, from the stage history), the same
// view the weekly report uses, so the two never disagree. The database counts them (insights_summary, 0024).

export const GROUPS = {
  segment: 'Segment',
  country: 'Country',
  signal: 'Signal type',
  pitch: 'Pitch mode',
  angle: 'Angle',
  test_group: 'Test group',
} as const
export type GroupKey = keyof typeof GROUPS

export type InsightFilters = { from: string; to: string; seg: string; country: string; group: GroupKey }

export function defaultRange(now: Date) {
  const to = istDate(now)
  return { from: addDays(to, -29), to }
}

/** Below this many contacted leads a rate is shown greyed as "too few to judge" (plan 15.6.7). */
export const MIN_SAMPLE = 30

/**
 * The Insights page in one database call: the funnel, the funnel by segment and by the chosen group, lead
 * quality and, for admins only, spend per day against the cap and the unit costs. Leads added on the India days
 * `from` to `to`, both included. Runs as the user (Row Level Security), so the page can start it before the
 * role is known.
 */
export async function getInsights(f: InsightFilters): Promise<Insights> {
  const sb = await createClient()
  const filters: Record<string, string> = { group: f.group }
  if (f.seg) filters.seg = f.seg
  if (f.country) filters.country = f.country
  const { data, error } = await sb.rpc('insights_summary', {
    from_ts: istMidnightUtc(f.from),
    to_ts: istMidnightUtc(addDays(f.to, 1)),
    filters,
  })
  if (error) throw error
  return toInsights(data)
}
