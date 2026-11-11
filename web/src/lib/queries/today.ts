import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { istDate, startOfMonthIst, startOfWeekIst } from '@/lib/dates'
import { CLOSED_STAGE_LIST } from '@/lib/stages'

export const TODAY_LIMIT = 100

/** Today's send list from v_today: new A and B leads, reachable, not skipped, best first (plan 15.6.3). */
export async function getSendList(limit = TODAY_LIMIT) {
  const sb = await createClient()
  const { data, error } = await sb
    .from('v_today')
    .select(
      'lead_id, company, city, segment_id, grade, total, channel, top_signal_type, top_signal_quote, top_signal_url, top_signal_at, contact_name, contact_role, phone_e164, phone_type, phone_source, email, email_subject, email_body, message',
    )
    .order('grade', { ascending: true })
    .order('total', { ascending: false, nullsFirst: false })
    .order('created_at', { ascending: true })
    .limit(limit)
  if (error) throw error
  return (data ?? []).flatMap((r) => (r.lead_id ? [{ ...r, lead_id: r.lead_id, company: r.company ?? 'Unnamed business' }] : []))
}

export type SendRow = Awaited<ReturnType<typeof getSendList>>[number]

/** Day 3 and day 7 follow-ups due today or earlier, with the phone type (WhatsApp is for mobiles only). */
export async function getFollowupsDue(limit = TODAY_LIMIT) {
  const sb = await createClient()
  const { data, error } = await sb
    .from('v_followups_due')
    .select('lead_id, company, segment_id, grade, contact_name, phone_e164, which, followup_text, due_on')
    .order('due_on', { ascending: true })
    .limit(limit)
  if (error) throw error
  const rows = (data ?? []).filter((r) => r.lead_id && r.due_on && (r.which === 'd3' || r.which === 'd7'))
  const ids = [...new Set(rows.map((r) => r.lead_id!))]
  const extra = new Map<string, { city: string | null; phone_type: string | null }>()
  if (ids.length) {
    const { data: more, error: moreError } = await sb.from('v_leads_caller').select('id, city, phone_type').in('id', ids)
    if (moreError) throw moreError
    for (const m of more ?? []) if (m.id) extra.set(m.id, { city: m.city, phone_type: m.phone_type })
  }
  return rows.map((r) => ({
    lead_id: r.lead_id!,
    company: r.company ?? 'Unnamed business',
    grade: r.grade,
    contact_name: r.contact_name,
    phone_e164: r.phone_e164,
    which: r.which as 'd3' | 'd7',
    followup_text: r.followup_text,
    due_on: r.due_on!,
    city: extra.get(r.lead_id!)?.city ?? null,
    phone_type: extra.get(r.lead_id!)?.phone_type ?? null,
  }))
}

export type FollowupRow = Awaited<ReturnType<typeof getFollowupsDue>>[number]

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
  const weekStart = istDate(new Date(startOfWeekIst(now)))
  const head = { count: 'exact' as const, head: true }
  const results = await Promise.all([
    sb.from('v_today').select('lead_id', head),
    sb.from('v_leads_caller').select('id', head).gte('wa_at', weekStart),
    sb.from('v_leads_caller').select('id', head).eq('stage', 'talking'),
    sb.from('v_leads_caller').select('id', head).in('stage', ['discovery_booked', 'discovery_done']),
    sb.from('v_leads_caller').select('id', head).eq('stage', 'proposal_sent'),
    sb.from('v_leads_caller').select('id', head).lt('due_at', today).not('stage', 'in', CLOSED_STAGE_LIST),
  ])
  for (const r of results) if (r.error) throw r.error
  const [ready, contacted, talking, discovery, proposals, overdue] = results.map((r) => r.count ?? 0) as [
    number,
    number,
    number,
    number,
    number,
    number,
  ]

  let wonThisMonthInr: number | null = null
  if (withMoney) {
    // Leads that moved to Won or Retainer this month (the stage_change rows are written by the database).
    const { data: events } = await sb
      .from('activities')
      .select('lead_id, payload')
      .eq('type', 'stage_change')
      .gte('at', startOfMonthIst(now))
      .limit(2000)
    const ids = [
      ...new Set(
        (events ?? [])
          .filter((a) => {
            const to = (a.payload as { to?: string } | null)?.to
            return to === 'won' || to === 'retainer'
          })
          .map((a) => a.lead_id),
      ),
    ]
    wonThisMonthInr = 0
    for (let i = 0; i < ids.length; i += 150) {
      const { data } = await sb.from('v_leads_admin').select('id, stage, deal_value_inr').in('id', ids.slice(i, i + 150))
      wonThisMonthInr += (data ?? [])
        .filter((r) => r.stage === 'won' || r.stage === 'retainer')
        .reduce((sum, r) => sum + Number(r.deal_value_inr ?? 0), 0)
    }
  }

  return { ready, contactedThisWeek: contacted, talking, discovery, proposals, overdue, wonThisMonthInr }
}
