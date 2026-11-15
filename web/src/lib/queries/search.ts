import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { toSearchResults, type SearchResult } from './page-data'

export type { SearchResult } from './page-data'

export const SEARCH_LIMIT = 10

/**
 * Leads by business name or website, typo tolerant, or by a phone's digits (search_leads, migration 0024):
 * best match first, at most `max` (50 at most). Fewer than 2 characters finds nothing. Any app role can search
 * every lead, as on the Leads page; the results carry no money, notes or messages.
 */
export async function searchLeads(q: string, max = SEARCH_LIMIT): Promise<SearchResult[]> {
  const term = q.trim()
  if (term.length < 2) return []
  const sb = await createClient()
  const { data, error } = await sb.rpc('search_leads', { q: term.slice(0, 80), max })
  if (error) throw error
  return toSearchResults(data)
}
