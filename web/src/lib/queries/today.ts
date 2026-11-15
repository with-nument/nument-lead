import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { toHomeSummary, type HomeSummary } from './page-data'

export type { FollowupRow, HomeSummary, SendRow, TodayKpis } from './page-data'

export const TODAY_LIMIT = 100

/**
 * Everything Today shows, in one database call (home_summary, migration 0024): the KPI counts, the send list
 * (v_today: new A and B leads, reachable, not skipped, best first, plan 15.6.3), the day 3 and day 7 follow-ups
 * due with their city and phone type, and the money won this month. Runs as the user under Row Level Security,
 * so the page can start it before the role is known: the money is in it only for admins (null for anyone else).
 */
export async function getHomeSummary(limit = TODAY_LIMIT): Promise<HomeSummary> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('home_summary', { list_limit: limit })
  if (error) throw error
  return toHomeSummary(data)
}
