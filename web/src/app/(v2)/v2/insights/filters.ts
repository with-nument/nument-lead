// The Insights filters from the address bar, and the bar maths. Pure, so they are unit tested.
import { addDays, daysBetween } from '@/lib/dates'

export const GROUP_KEYS = ['segment', 'country', 'signal', 'pitch', 'angle', 'test_group'] as const
export type GroupKeyV2 = (typeof GROUP_KEYS)[number]
export const PERIODS = ['7', '30', '90'] as const
export type Period = (typeof PERIODS)[number]

export type InsightsQuery = { period: Period; from: string; to: string; seg: string; country: string; group: GroupKeyV2 }

const one = (sp: Record<string, string | string[] | undefined>, k: string) => (typeof sp[k] === 'string' ? (sp[k] as string) : '')

/** The filters for the India day `today`: the last 7, 30 (default) or 90 days, a segment, a country, a grouping. */
export function parseInsightsQuery(sp: Record<string, string | string[] | undefined>, today: string): InsightsQuery {
  const days = one(sp, 'days')
  const period = (PERIODS as readonly string[]).includes(days) ? (days as Period) : '30'
  const group = one(sp, 'group')
  const from = addDays(today, -(Number(period) - 1))
  return {
    period,
    from: daysBetween(from, today) > 366 ? addDays(today, -366) : from,
    to: today,
    seg: /^[a-z0-9-]{1,40}$/.test(one(sp, 'seg')) ? one(sp, 'seg') : '',
    country: /^[a-z]{2}$/.test(one(sp, 'country')) ? one(sp, 'country') : '',
    group: (GROUP_KEYS as readonly string[]).includes(group) ? (group as GroupKeyV2) : 'segment',
  }
}

/** The address-bar query for a set of filters, leaving out defaults. */
export function insightsHref(q: Pick<InsightsQuery, 'period' | 'seg' | 'country' | 'group'>) {
  const p = new URLSearchParams()
  if (q.period !== '30') p.set('days', q.period)
  if (q.seg) p.set('seg', q.seg)
  if (q.country) p.set('country', q.country)
  if (q.group !== 'segment') p.set('group', q.group)
  const s = p.toString()
  return s ? `/insights?${s}` : '/insights'
}

/** A bar's width as a share of the largest value, 0..1; a non-zero value always shows a sliver. */
export function barShare(value: number, max: number) {
  if (max <= 0 || value <= 0) return 0
  return Math.max(0.02, Math.min(1, value / max))
}

/** "34%" of the whole, or empty when the whole is 0. */
export function pct(part: number, whole: number) {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : ''
}
