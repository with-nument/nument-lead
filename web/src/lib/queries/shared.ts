import 'server-only'
import { cache } from 'react'
import { createAdminClient } from '@/lib/supabase/admin'
import { createClient } from '@/lib/supabase/server'
import { segmentFallbackLabel } from '@/lib/signals'

export type Segment = { id: string; label: string; country: string; domain: string; enabled: boolean; daily_quota: number }

/** Segments for filters and labels. Readable by every role. */
export const getSegments = cache(async (): Promise<Segment[]> => {
  const sb = await createClient()
  const { data, error } = await sb
    .from('segments')
    .select('id, display_name, country, domain, enabled, daily_quota')
    .order('id')
  if (error) throw error
  return (data ?? []).map((s) => ({
    id: s.id,
    label: s.display_name || segmentFallbackLabel(s.id),
    country: s.country.trim(),
    domain: s.domain,
    enabled: s.enabled,
    daily_quota: s.daily_quota,
  }))
})

export const segmentLabeler = (segments: Segment[]) => {
  const map = new Map(segments.map((s) => [s.id, s.label]))
  return (id: string | null | undefined) => (id ? (map.get(id) ?? segmentFallbackLabel(id)) : '')
}

export type TeamMember = { id: string; name: string; role: string }

/**
 * Team names for timelines and owner columns. Profiles are private to each user under RLS,
 * so names (and only names and roles) are read with the service role after the page checked the session.
 */
export const getTeam = cache(async (): Promise<TeamMember[]> => {
  const admin = createAdminClient()
  const { data, error } = await admin.from('profiles').select('user_id, full_name, role').order('full_name')
  if (error) throw error
  return (data ?? []).map((p) => ({ id: p.user_id, name: p.full_name?.trim() || 'Team member', role: p.role }))
})
