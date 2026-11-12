import 'server-only'
import { cacheLife, cacheTag } from 'next/cache'
import { TAGS } from '@/lib/cache-tags'
import { createAdminClient } from '@/lib/supabase/admin'
import { segmentFallbackLabel } from '@/lib/signals'

export type Segment = { id: string; label: string; country: string; domain: string; enabled: boolean; daily_quota: number }

/**
 * Segments for filters and labels. Every app role reads the same rows (RLS `segments_read`), so they are
 * read once with the service role and cached for everyone, after the page has checked the session.
 * The Engine page actions that switch a segment or change its quota update the tag.
 */
export async function getSegments(): Promise<Segment[]> {
  'use cache'
  cacheLife('hours')
  cacheTag(TAGS.segments)
  const sb = createAdminClient()
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
}

export const segmentLabeler = (segments: Segment[]) => {
  const map = new Map(segments.map((s) => [s.id, s.label]))
  return (id: string | null | undefined) => (id ? (map.get(id) ?? segmentFallbackLabel(id)) : '')
}

export type TeamMember = { id: string; name: string; role: string }

/**
 * Team names for timelines and owner columns. Profiles are private to each user under RLS,
 * so names (and only names and roles) are read with the service role after the page checked the session.
 * The same list for everyone, cached; a name change, a new user or a role change updates the tag.
 */
export async function getTeam(): Promise<TeamMember[]> {
  'use cache'
  cacheLife('hours')
  cacheTag(TAGS.team)
  const admin = createAdminClient()
  const { data, error } = await admin.from('profiles').select('user_id, full_name, role').order('full_name')
  if (error) throw error
  return (data ?? []).map((p) => ({ id: p.user_id, name: p.full_name?.trim() || 'Team member', role: p.role }))
}
