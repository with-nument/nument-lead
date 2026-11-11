import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { addDays, daysBetween, istDate, istMidnightUtc } from '@/lib/dates'

// Funnel numbers come from v_funnel (furthest stage each lead ever reached, from the stage history),
// the same view the weekly report uses, so the two never disagree.

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

export type Counts = { leads: number; contacted: number; replied: number; meetings: number; proposals: number; won: number }
const emptyCounts = (): Counts => ({ leads: 0, contacted: 0, replied: 0, meetings: 0, proposals: 0, won: 0 })

export function defaultRange(now: Date) {
  const to = istDate(now)
  return { from: addDays(to, -29), to }
}

/** Below this many contacted leads a rate is shown greyed as "too few to judge" (plan 15.6.7). */
export const MIN_SAMPLE = 30

export async function getInsights(f: InsightFilters) {
  const sb = await createClient()
  let funnelQuery = sb
    .from('v_funnel')
    .select('lead_id, segment_id, country, pitch_mode, angle, test_group, top_signal_type, reached_contacted, reached_talking, reached_discovery, reached_proposal, reached_won')
    .gte('created_on', f.from)
    .lte('created_on', f.to)
  if (f.seg) funnelQuery = funnelQuery.eq('segment_id', f.seg)
  if (f.country) funnelQuery = funnelQuery.eq('country', f.country)

  let leadsQuery = sb
    .from('v_leads_caller')
    .select('id, stage, phone_e164, phone_source, top_signal_at, created_at')
    .gte('created_at', istMidnightUtc(f.from))
    .lt('created_at', istMidnightUtc(addDays(f.to, 1)))
  if (f.seg) leadsQuery = leadsQuery.eq('segment_id', f.seg)
  if (f.country) leadsQuery = leadsQuery.eq('country', f.country)

  const [funnel, leads] = await Promise.all([funnelQuery.limit(10_000), leadsQuery.limit(10_000)])
  if (funnel.error) throw funnel.error
  if (leads.error) throw leads.error

  const total = emptyCounts()
  const bySegment = new Map<string, Counts>()
  const byGroup = new Map<string, Counts>()
  const bump = (c: Counts, r: NonNullable<typeof funnel.data>[number]) => {
    c.leads++
    if (r.reached_contacted) c.contacted++
    if (r.reached_talking) c.replied++
    if (r.reached_discovery) c.meetings++
    if (r.reached_proposal) c.proposals++
    if (r.reached_won) c.won++
  }
  for (const r of funnel.data ?? []) {
    bump(total, r)
    const seg = r.segment_id ?? 'unknown'
    if (!bySegment.has(seg)) bySegment.set(seg, emptyCounts())
    bump(bySegment.get(seg)!, r)
    const key =
      f.group === 'segment'
        ? seg
        : f.group === 'country'
          ? r.country
          : f.group === 'signal'
            ? (r.top_signal_type ?? 'none')
            : f.group === 'pitch'
              ? r.pitch_mode
              : f.group === 'angle'
                ? r.angle
                : r.test_group
    const k = key?.trim() || 'unknown'
    if (!byGroup.has(k)) byGroup.set(k, emptyCounts())
    bump(byGroup.get(k)!, r)
  }

  // Lead quality.
  const rows = leads.data ?? []
  let withPhone = 0
  let ownPhone = 0
  let contacted = 0
  let wrong = 0
  const ages: number[] = []
  for (const l of rows) {
    if (l.phone_e164) withPhone++
    if (l.phone_e164 && l.phone_source === 'website') ownPhone++
    if (l.stage && l.stage !== 'new') contacted++
    if (l.stage === 'wrong_contact') wrong++
    if (l.top_signal_at && l.created_at) ages.push(Math.max(0, daysBetween(istDate(l.top_signal_at), istDate(l.created_at))))
  }
  ages.sort((a, b) => a - b)
  const median = ages.length
    ? ages.length % 2
      ? ages[(ages.length - 1) / 2]!
      : (ages[ages.length / 2 - 1]! + ages[ages.length / 2]!) / 2
    : null

  let up = 0
  let votes = 0
  const ids = rows.map((l) => l.id!).filter(Boolean)
  for (let i = 0; i < ids.length; i += 150) {
    const { data: fb } = await sb.from('feedback').select('rating').in('lead_id', ids.slice(i, i + 150))
    for (const r of fb ?? []) {
      votes++
      if (r.rating > 0) up++
    }
  }

  return {
    total,
    bySegment: [...bySegment.entries()].map(([id, c]) => ({ id, ...c })).sort((a, b) => b.contacted - a.contacted || b.leads - a.leads),
    byGroup: [...byGroup.entries()].map(([id, c]) => ({ id, ...c })).sort((a, b) => b.contacted - a.contacted || b.leads - a.leads),
    quality: {
      leads: rows.length,
      phoneRate: rows.length ? withPhone / rows.length : null,
      ownPhoneRate: rows.length ? ownPhone / rows.length : null,
      wrongRate: contacted ? wrong / contacted : null,
      medianSignalAgeDays: median,
      thumbsUpRate: votes ? up / votes : null,
      votes,
    },
  }
}

export type CostDay = { day: string; inr: number }

/** Spend per day against the cap, and unit costs. Admin only (costs are admin-only under RLS). */
export async function getCosts(f: InsightFilters) {
  const sb = await createClient()
  const [costs, cap, researched, goodLeads, won] = await Promise.all([
    sb.from('v_costs_daily').select('day, inr').gte('day', f.from).lte('day', f.to).limit(5000),
    sb.from('settings').select('value').eq('key', 'daily_cap_inr').maybeSingle(),
    sb
      .from('businesses')
      .select('id', { count: 'exact', head: true })
      .gte('researched_at', istMidnightUtc(f.from))
      .lt('researched_at', istMidnightUtc(addDays(f.to, 1))),
    sb
      .from('v_leads_caller')
      .select('id', { count: 'exact', head: true })
      .in('grade', ['A', 'B'])
      .gte('created_at', istMidnightUtc(f.from))
      .lt('created_at', istMidnightUtc(addDays(f.to, 1))),
    sb
      .from('v_funnel')
      .select('lead_id', { count: 'exact', head: true })
      .eq('reached_won', true)
      .gte('created_on', f.from)
      .lte('created_on', f.to),
  ])
  if (costs.error) throw costs.error
  const perDay = new Map<string, number>()
  for (const r of costs.data ?? []) if (r.day) perDay.set(r.day, (perDay.get(r.day) ?? 0) + Number(r.inr ?? 0))
  const days: CostDay[] = []
  for (let d = f.from; d <= f.to; d = addDays(d, 1)) days.push({ day: d, inr: Math.round((perDay.get(d) ?? 0) * 100) / 100 })
  const spend = days.reduce((s, d) => s + d.inr, 0)
  const capValue = Number(cap.data?.value ?? 750)
  const per = (n: number | null) => (n && n > 0 ? spend / n : null)
  return {
    days,
    cap: Number.isFinite(capValue) && capValue > 0 ? capValue : 750,
    spend,
    perResearched: per(researched.count),
    perGoodLead: per(goodLeads.count),
    perWon: per(won.count),
    researched: researched.count ?? 0,
    goodLeads: goodLeads.count ?? 0,
    won: won.count ?? 0,
  }
}
