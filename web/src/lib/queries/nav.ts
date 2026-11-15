import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { toNavCounts, type NavCounts } from './page-data'

export type { NavCounts } from './page-data'

/**
 * Small numbers for the navigation (nav_counts, migration 0024): leads ready to send, follow-ups due, overdue
 * leads, open deals and, for admins, new Inbox posts. One database call; it works through v_today and
 * v_followups_due like the Today page, so on Today itself use the counts that come with getHomeSummary instead.
 */
export async function getNavCounts(): Promise<NavCounts> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('nav_counts')
  if (error) throw error
  return toNavCounts(data)
}
