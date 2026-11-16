'use server'

import { requireUser } from '@/lib/auth'
import { searchLeads, type SearchResult } from '@/lib/queries/search'

export type SearchAnswer = { ok: true; results: SearchResult[] } | { ok: false; results: [] }

/** The ⌘K menu's lead search: by name, website or phone digits (search_leads), as the signed-in user. */
export async function searchLeadsAction(query: string): Promise<SearchAnswer> {
  await requireUser()
  try {
    return { ok: true, results: await searchLeads(typeof query === 'string' ? query : '') }
  } catch {
    return { ok: false, results: [] }
  }
}
