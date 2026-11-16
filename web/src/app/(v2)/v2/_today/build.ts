// From home_summary to the Today sections. Pure, so it is unit tested (tests/unit/today-v2.test.ts).
import { dueState } from '@/lib/dates'
import { formatInr, formatNumber } from '@/lib/format'
import type { HomeSummary } from '@/lib/queries/page-data'
import { signalLabel } from '@/lib/signals'
import type { CallItem, FollowupItem, OvernightStat, ProposalItem, ReplyItem, StartupItem, TodayStep } from './types'

export type TodayData = {
  replies: ReplyItem[]
  calls: CallItem[]
  proposals: ProposalItem[]
  followups: FollowupItem[]
  startups: StartupItem[]
}

export function followupsFrom(summary: HomeSummary, today: string): FollowupItem[] {
  return summary.followups.map((f) => {
    const state = dueState(f.due_on, today)
    const day = f.which === 'd3' ? 'Day 3' : 'Day 7'
    return {
      leadId: f.lead_id,
      company: f.company,
      person: f.contact_name,
      which: f.which,
      overdue: state === 'overdue',
      note: `${day} follow-up · ${state === 'overdue' ? 'overdue' : 'due today'}`,
    }
  })
}

export function startupsFrom(summary: HomeSummary): StartupItem[] {
  return summary.send.map((r) => ({
    leadId: r.lead_id,
    company: r.company,
    grade: r.grade,
    city: r.city,
    person: r.contact_name,
    signal: r.top_signal_type ? [signalLabel(r.top_signal_type), r.top_signal_quote ? `“${r.top_signal_quote}”` : null].filter(Boolean).join(' · ') : null,
  }))
}

/** "All grade A or B · 3 with a verified email": what the batch has in common, from the rows themselves. */
export function startupSummary(summary: HomeSummary): string | undefined {
  const rows = summary.send
  if (!rows.length) return undefined
  const grades = new Set(rows.map((r) => r.grade ?? 'D'))
  const parts: string[] = []
  if ([...grades].every((g) => g === 'A' || g === 'B')) parts.push(grades.size === 1 ? `All grade ${[...grades][0]}` : 'All grade A or B')
  const withEmail = rows.filter((r) => r.email).length
  if (withEmail) parts.push(withEmail === rows.length ? 'all have an email' : `${formatNumber(withEmail)} with an email`)
  const withPhone = rows.filter((r) => r.phone_e164).length
  if (withPhone) parts.push(`${formatNumber(withPhone)} with a published phone`)
  return parts.join(' · ') || undefined
}

/** The section that holds the page's one solid button: the first with something to do. */
export function firstStep(d: TodayData): TodayStep | null {
  if (d.replies.length) return 'replies'
  if (d.calls.length) return 'calls'
  if (d.proposals.length) return 'proposals'
  if (d.followups.length) return 'followups'
  if (d.startups.length) return 'startups'
  return null
}

/** How many things need the person: each reply, call, proposal and follow-up, and the startup batch as one. */
export const thingsToDo = (d: TodayData) => d.replies.length + d.calls.length + d.proposals.length + d.followups.length + (d.startups.length ? 1 : 0)

const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`

/** Good morning, afternoon or evening, by the hour in India. */
export function greeting(now: Date): string {
  const hour = Number(new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone: 'Asia/Kolkata' }).format(now))
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
}

/** The page title, its phone version and the one sentence under it. */
export function headline(d: TodayData, now: Date): { title: string; compact: string; subtitle: string } {
  const n = thingsToDo(d)
  const hello = greeting(now)
  if (n === 0) {
    return {
      title: `${hello}. Nothing needs you right now.`,
      compact: 'All caught up',
      subtitle: 'New startups arrive each morning. Replies show up here as soon as they come in.',
    }
  }
  const things = `${plural(n, 'thing needs', 'things need')} you`
  const step = firstStep(d)
  const start =
    step === 'replies'
      ? `Start with ${plural(d.replies.length, 'reply', 'replies')}.`
      : step === 'calls'
        ? 'Start with your calls.'
        : step === 'proposals'
          ? `Start with ${plural(d.proposals.length, 'proposal', 'proposals')} to send.`
          : step === 'followups'
            ? `Start with ${plural(d.followups.length, 'follow-up', 'follow-ups')}.`
            : `Start with ${plural(d.startups.length, 'new startup', 'new startups')} to contact.`
  const call = d.calls[0] && step !== 'calls' ? ` Your first call is at ${d.calls[0].time}.` : d.calls[0] ? ` The first is at ${d.calls[0].time}.` : ''
  return { title: `${hello}. ${things} today.`, compact: things, subtitle: `${start}${call}` }
}

/** The numbers card, from what home_summary counts today. The email work adds the overnight numbers later. */
export function pipelineStats(summary: HomeSummary): OvernightStat[] {
  const k = summary.kpis
  const rows: OvernightStat[] = [
    { label: 'Ready to contact', value: formatNumber(k.ready) },
    { label: 'Contacted this week', value: formatNumber(k.contactedThisWeek) },
    { label: 'Replied', value: formatNumber(k.talking) },
    { label: 'Calls', value: formatNumber(k.discovery) },
    { label: 'Proposals out', value: formatNumber(k.proposals) },
  ]
  if (k.wonThisMonthInr !== null) rows.push({ label: 'Won this month', value: formatInr(k.wonThisMonthInr) })
  return rows
}
