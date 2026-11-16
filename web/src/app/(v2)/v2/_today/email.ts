// From the email functions (inbox_page, calls_page: migration 0033) and today_overnight (0034) to the Today
// sections. Pure, so it is unit tested (tests/unit/today-email.test.ts). Never counts email opens: the app does
// not track them.
import type { Json } from '@/lib/database.types'
import { addDays, formatDate, formatTime, istDate, TIME_ZONE } from '@/lib/dates'
import { formatNumber, formatPercent } from '@/lib/format'
import { rangeText, type Call, type CallsPage, type InboxItem } from '@/lib/queries/email-data'
import type { CallItem, OvernightHealth, OvernightStat, ProposalItem, ReplyItem } from './types'

const GREETING = /^(hi|hello|hey|dear|thanks|thank you)\b[^.!?\n]{0,40}[,!]?\s*$/i
const SIGNED_NAME = /^\p{L}[\p{L}'’ -]{0,30}$/u
const SIGNOFF = /^(best|thanks|regards|cheers|warm regards|kind regards|team nument)\b/i

/** One short line from an email: no greeting line, no sign-off, spaces collapsed, cut at a word. */
export function excerpt(body: string | null | undefined, max = 160): string {
  if (!body) return ''
  const lines = body
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean)
  while (lines.length > 1 && GREETING.test(lines[0]!)) lines.shift()
  const end = lines.findIndex((l, i) => i > 0 && SIGNOFF.test(l))
  const rest = end > 0 ? lines.slice(0, end) : lines
  // A last line of one to three words with no sentence mark is a signed name ("Maya", "Dev M").
  const last = rest.at(-1) ?? ''
  if (rest.length > 1 && SIGNED_NAME.test(last) && last.split(' ').length <= 3) rest.pop()
  const kept = rest.join(' ').replace(/\s+/g, ' ').trim()
  if (kept.length <= max) return kept
  const cut = kept.slice(0, max - 1)
  const space = cut.lastIndexOf(' ')
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.]+$/, '')}…`
}

/**
 * Replies waiting for a person (inbox_page 'replies'). The row's id is the drafted answer's message id, which
 * Approve sends to review_message; a reply with no drafted answer can only be opened.
 */
export function repliesFrom(items: InboxItem[]): ReplyItem[] {
  return items.map((i) => {
    const draft = i.draft && (i.draft.status === 'draft' || i.draft.status === 'review') && i.draft.body.trim() ? i.draft : null
    return {
      id: draft?.id ?? i.key,
      leadId: i.leadId,
      person: i.contactName ?? i.company,
      company: i.company,
      quote: excerpt(i.inbound?.body) || 'Replied',
      suggestion: draft ? excerpt(draft.body, 120) : null,
      approvable: draft !== null,
    }
  })
}

/** "Brief ready · Upload a contract and flag risky clauses", or why there is none yet. */
function callNote(c: Call): string {
  const brief = c.brief?.content
  const what = brief?.whatTheyNeed[0] ?? c.offer?.name ?? null
  const plan = c.plan?.views ? `plan viewed ${c.plan.views === 1 ? 'once' : `${formatNumber(c.plan.views)} times`}` : null
  if (brief) return ['Brief ready', what, plan].filter(Boolean).join(' · ')
  return ['Brief on its way', plan].filter(Boolean).join(' · ')
}

/** Calls booked for today (calls_page 'today'), earliest first. "Open brief" opens it on the Calls page. */
export function callsFrom(page: CallsPage): CallItem[] {
  return [...page.today]
    .sort((a, b) => a.meetingAt.localeCompare(b.meetingAt))
    .map((c) => ({
      id: `${c.leadId}-${c.meetingAt}`,
      leadId: c.leadId,
      time: c.meetingAt ? formatTime(c.meetingAt) : '',
      person: c.contactName ?? c.company,
      company: c.company,
      note: callNote(c),
      href: `/calls?lead=${c.leadId}`,
    }))
}

const WEEKDAY = new Intl.DateTimeFormat('en-IN', { weekday: 'long', timeZone: TIME_ZONE })

/** "Friday's call", "today's call", or "the call on 2 Nov" for an older one. */
function callDay(iso: string, now: Date): string {
  const day = istDate(iso)
  const today = istDate(now)
  if (day === today) return 'today’s call'
  if (day === addDays(today, -1)) return 'yesterday’s call'
  if (day >= addDays(today, -6) && day < today) return `${WEEKDAY.format(new Date(iso))}’s call`
  return `the call on ${formatDate(iso, now)}`
}

/**
 * Proposals the engine has written from a call's notes and nobody has sent yet (a draft with content), from
 * every call calls_page lists, newest call first.
 */
export function proposalsFrom(page: CallsPage, now: Date): ProposalItem[] {
  return [...page.today, ...page.upcoming, ...page.earlier]
    .filter((c) => c.proposal && c.proposal.status === 'draft' && c.proposal.drafted)
    .sort((a, b) => b.meetingAt.localeCompare(a.meetingAt))
    .map((c) => {
      const offer = c.offer ? [c.offer.name, c.offer.timeline].filter(Boolean).join(', ') : null
      const range = c.offer ? rangeText(c.offer.range) : ''
      return {
        id: c.proposal!.id,
        leadId: c.leadId,
        company: c.company,
        person: c.contactName,
        note: [c.meetingAt ? `Drafted from ${callDay(c.meetingAt, now)}` : 'Drafted', offer, range].filter(Boolean).join(' · '),
      }
    })
}

/* ------------------------------------------------------------------------------------------------------------
 * The Overnight card: today_overnight() (0034)
 * ---------------------------------------------------------------------------------------------------------- */

export type Overnight = {
  since: string | null
  startupsFound: number
  startupsQualified: number
  emailsSent: number
  replies: number
  planPagesViewed: number
  bounced: number
}

const n = (v: unknown) => {
  const x = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(x) && x > 0 ? x : 0
}

export function toOvernight(data: Json | null): Overnight | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const d = data as Record<string, unknown>
  return {
    since: typeof d.since === 'string' ? d.since : null,
    startupsFound: n(d.startups_found),
    startupsQualified: n(d.startups_qualified),
    emailsSent: n(d.emails_sent),
    replies: n(d.replies),
    planPagesViewed: n(d.plan_pages_viewed),
    bounced: n(d.bounced),
  }
}

export function overnightStats(o: Overnight): OvernightStat[] {
  return [
    { label: 'Startups found', value: formatNumber(o.startupsFound) },
    { label: 'Passed every check', value: formatNumber(o.startupsQualified) },
    { label: 'Emails sent', value: formatNumber(o.emailsSent) },
    { label: 'Replies', value: formatNumber(o.replies) },
    { label: 'Plan pages viewed', value: formatNumber(o.planPagesViewed) },
  ]
}

/** Sending health from the bounce rate; the engine pauses sending at 3% (outreach.bounce_pause_pct). */
export function overnightHealth(o: Overnight): OvernightHealth | null {
  if (!o.emailsSent) return null
  const ratio = o.bounced / o.emailsSent
  const pct = formatPercent(ratio, ratio > 0 && ratio < 0.1 ? 1 : 0)
  if (ratio >= 0.03) return { tone: 'bad', text: `Too many bounces · ${pct} bounced` }
  if (ratio >= 0.02) return { tone: 'warn', text: `Bounces are rising · ${pct} bounced` }
  return { tone: 'ok', text: `Sending is healthy · ${pct} bounced` }
}
