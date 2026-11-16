// The v2 Leads list: the scope tabs as plain filter sets, and rows as display-ready values. Pure, so it is
// unit tested (tests/unit/lead-v2-model.test.ts). The URL stays the same filter language as before
// (lib/leads-filters), so old links and saved views open the same leads.
import { addDays, formatDate, istDate } from '@/lib/dates'
import { EMPTY_FILTERS, type LeadFilters } from '@/lib/leads-filters'
import type { LeadListRow } from '@/lib/queries/page-data'
import { signalLabel } from '@/lib/signals'
import type { DotTone } from '../_ui/marks'

export type Scope = 'all' | 'new' | 'a' | 'replied' | 'not_contacted'

export const SCOPES: { value: Scope; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'a', label: 'Grade A' },
  { value: 'replied', label: 'Replied' },
  { value: 'not_contacted', label: 'Not contacted' },
]

/** The filters a scope tab sets. New means found since yesterday (India time). The search is kept. */
export function scopeFilters(scope: Scope, q: string, now: Date = new Date()): LeadFilters {
  const base: LeadFilters = { ...EMPTY_FILTERS, q }
  switch (scope) {
    case 'new':
      return { ...base, from: addDays(istDate(now), -1) }
    case 'a':
      return { ...base, grade: ['A'] }
    case 'replied':
      return { ...base, stage: ['talking'] }
    case 'not_contacted':
      return { ...base, stage: ['new'] }
    default:
      return base
  }
}

const same = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x, i) => x === b[i])

/** Which tab the filters are, or null when they are a custom mix (the Filter button shows how many). */
export function scopeOf(f: LeadFilters, now: Date = new Date()): Scope | null {
  for (const s of SCOPES) {
    const want = scopeFilters(s.value, f.q, now)
    const keys = ['seg', 'country', 'city', 'grade', 'signal', 'stage', 'pitch'] as const
    if (
      keys.every((k) => same(want[k], f[k])) &&
      want.mobile === f.mobile &&
      want.overdue === f.overdue &&
      want.owner === f.owner &&
      want.from === f.from &&
      want.to === f.to
    )
      return s.value
  }
  return null
}

/** Filters set beyond the search and the scope's own (for the Filter button's count). */
export function extraFilterCount(f: LeadFilters): number {
  return (
    [f.seg, f.country, f.city, f.grade, f.signal, f.stage, f.pitch].filter((a) => a.length > 0).length +
    [f.mobile, f.overdue, Boolean(f.owner), Boolean(f.from || f.to), f.sort !== 'created' || f.dir !== 'desc'].filter(Boolean).length
  )
}

export type LeadRowV2 = {
  id: string
  name: string
  sub: string
  grade: string | null
  stage: string
  why: string
  contact: { tone: DotTone; text: string }
  found: string
}

/** What the Contact column says: only a number the company published counts; the email lives on the lead. */
export function contactOf(r: Pick<LeadListRow, 'phone_e164' | 'phone_type' | 'contact_name'>): { tone: DotTone; text: string } {
  if (r.phone_e164) return { tone: 'ok', text: r.phone_type === 'mobile' ? 'Mobile published' : 'Phone published' }
  if (r.contact_name) return { tone: 'warn', text: 'Name, no number yet' }
  return { tone: 'none', text: 'No contact found' }
}

export function toRow(r: LeadListRow, segmentOf: (id: string | null) => string, now: Date): LeadRowV2 {
  return {
    id: r.id,
    name: r.name,
    sub: [segmentOf(r.segment_id), r.city].filter(Boolean).join(' · '),
    grade: r.grade,
    stage: r.stage,
    why: r.top_signal_quote?.trim() || (r.top_signal_type ? signalLabel(r.top_signal_type) : ''),
    contact: contactOf(r),
    found: r.created_at ? formatDate(r.created_at, now) : '',
  }
}
