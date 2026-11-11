import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { startOfMonthIst, startOfWeekIst, istDate } from '@/lib/dates'
import { CLOSED_STAGE_LIST } from '@/lib/stages'
import { getTopSignals, type TopSignal } from './shared'

export const TODAY_LIMIT = 100

const SEND_COLUMNS =
  'lead_id, business_id, business_name, city, country, segment_id, grade, score_total, pitch_mode, angle, channel, contact_name, contact_role, phone_e164, phone_type, contact_source, email, message, created_at' as const

export type SendRow = {
  lead_id: string
  business_id: string
  business_name: string
  city: string | null
  country: string | null
  segment_id: string | null
  grade: string | null
  score_total: number | null
  pitch_mode: string | null
  angle: string | null
  channel: string | null
  contact_name: string | null
  contact_role: string | null
  phone_e164: string | null
  phone_type: string | null
  contact_source: string | null
  email: string | null
  message: string | null
  created_at: string | null
  signal: TopSignal | null
}

/** Today's send list: new A and B leads, best first (plan 15.6.3). */
export async function getSendList(limit = TODAY_LIMIT): Promise<SendRow[]> {
  const sb = await createClient()
  const { data, error } = await sb
    .from('v_today')
    .select(SEND_COLUMNS)
    .order('grade', { ascending: true })
    .order('score_total', { ascending: false, nullsFirst: false })
    .order('created_at', { ascending: true })
    .limit(limit)
  if (error) throw error
  const rows = (data ?? []).filter((r) => r.lead_id && r.business_id)
  const signals = await getTopSignals(sb, rows.map((r) => r.business_id!))
  return rows.map((r) => ({
    ...r,
    lead_id: r.lead_id!,
    business_id: r.business_id!,
    business_name: r.business_name ?? 'Unnamed business',
    signal: signals.get(r.business_id!) ?? null,
  }))
}

export type FollowupRow = {
  lead_id: string
  business_name: string
  city: string | null
  stage: string
  next_step: string | null
  due_at: string
  phone_e164: string | null
  phone_type: string | null
  contact_name: string | null
  followup_d3: string | null
  followup_d7: string | null
  d3_at: string | null
  d7_at: string | null
  wa_at: string | null
}

/** Open leads whose next step is due today or earlier. */
export async function getFollowupsDue(limit = TODAY_LIMIT): Promise<FollowupRow[]> {
  const sb = await createClient()
  const { data, error } = await sb
    .from('v_followups_due')
    .select('lead_id, business_name, city, stage, next_step, due_at, phone_e164, phone_type, contact_name, followup_d3, followup_d7, d3_at, d7_at, wa_at')
    .order('due_at', { ascending: true })
    .order('score_total', { ascending: false, nullsFirst: false })
    .limit(limit)
  if (error) throw error
  return (data ?? [])
    .filter((r) => r.lead_id && r.due_at)
    .map((r) => ({
      ...r,
      lead_id: r.lead_id!,
      business_name: r.business_name ?? 'Unnamed business',
      stage: r.stage ?? 'contacted',
      due_at: r.due_at!,
    }))
}

export type TodayKpis = {
  ready: number
  contactedThisWeek: number
  talking: number
  discovery: number
  proposals: number
  overdue: number
  wonThisMonthInr: number | null
}

/** Numbers for the KPI tiles. Money only for admins, read through the admin view. */
export async function getTodayKpis(withMoney: boolean): Promise<TodayKpis> {
  const sb = await createClient()
  const now = new Date()
  const today = istDate(now)
  const head = { count: 'exact' as const, head: true }
  const [ready, contacted, talking, discovery, proposals, overdue] = await Promise.all([
    sb.from('v_today').select('lead_id', head),
    sb.from('v_leads_caller').select('lead_id', head).gte('wa_at', weekStartDay(now)),
    sb.from('v_leads_caller').select('lead_id', head).eq('stage', 'talking'),
    sb.from('v_leads_caller').select('lead_id', head).in('stage', ['discovery_booked', 'discovery_done']),
    sb.from('v_leads_caller').select('lead_id', head).eq('stage', 'proposal_sent'),
    sb.from('v_leads_caller').select('lead_id', head).lt('due_at', today).not('stage', 'in', CLOSED_STAGE_LIST),
  ])
  for (const r of [ready, contacted, talking, discovery, proposals, overdue]) if (r.error) throw r.error

  let wonThisMonthInr: number | null = null
  if (withMoney) {
    const { data: wonEvents } = await sb
      .from('activities')
      .select('lead_id, payload')
      .eq('type', 'stage_change')
      .gte('at', startOfMonthIst(now))
      .limit(1000)
    const ids = [
      ...new Set(
        (wonEvents ?? [])
          .filter((a) => {
            const to = (a.payload as { to?: string } | null)?.to
            return to === 'won' || to === 'retainer'
          })
          .map((a) => a.lead_id),
      ),
    ]
    wonThisMonthInr = 0
    if (ids.length) {
      const { data } = await sb.from('v_leads_admin').select('lead_id, stage, deal_value_inr').in('lead_id', ids.slice(0, 200))
      wonThisMonthInr = (data ?? [])
        .filter((r) => r.stage === 'won' || r.stage === 'retainer')
        .reduce((sum, r) => sum + Number(r.deal_value_inr ?? 0), 0)
    }
  }

  return {
    ready: ready.count ?? 0,
    contactedThisWeek: contacted.count ?? 0,
    talking: talking.count ?? 0,
    discovery: discovery.count ?? 0,
    proposals: proposals.count ?? 0,
    overdue: overdue.count ?? 0,
    wonThisMonthInr,
  }
}

/** Monday of this week in India, as "YYYY-MM-DD" (wa_at is a date column). */
function weekStartDay(now: Date) {
  return istDate(new Date(startOfWeekIst(now)))
}
