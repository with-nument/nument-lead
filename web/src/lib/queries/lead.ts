import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { toLeadDetail, type LeadDetail } from './page-data'

export type { LeadDetail } from './page-data'

/**
 * Everything the lead page shows, in one database call (lead_detail, migration 0024): the lead, its business,
 * contacts, signals, facts, latest score, pages, timeline and feedback, the Do not contact check for the
 * contacts' phones and, for admins only, the deal value, retainer and currency. Null when the lead is not
 * visible to this user. Runs as the user (Row Level Security), so the page can start it before the role is
 * known. Unverified facts are an admin view: the database returns them only when an admin asks.
 */
export async function getLeadDetail(leadId: string, opts: { includeUnverified: boolean }): Promise<LeadDetail | null> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('lead_detail', { lead_id: leadId, include_unverified: opts.includeUnverified })
  if (error) throw error
  return toLeadDetail(data)
}

/** Proposal files for a lead (private bucket; links are signed for 60 seconds when opened). */
export async function getProposals(leadId: string) {
  const sb = await createClient()
  const { data, error } = await sb.storage.from('proposals').list(leadId, { limit: 50, sortBy: { column: 'created_at', order: 'desc' } })
  if (error) return []
  return (data ?? [])
    .filter((f) => f.name && !f.name.startsWith('.'))
    .map((f) => ({
      path: `${leadId}/${f.name}`,
      name: f.name.replace(/^\d+-/, ''),
      size: Number((f.metadata as { size?: number } | null)?.size ?? 0),
      createdAt: f.created_at ?? null,
    }))
}
