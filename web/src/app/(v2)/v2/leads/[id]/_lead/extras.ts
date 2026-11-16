// From lead_conversation (migration 0033) to what the v2 lead page shows on top of lead_detail: the email
// thread with the suggested reply, the best offer, the startup profile with its evidence, plan page views and the
// email status. Pure, so it is unit tested (tests/unit/lead-extras.test.ts). Never shows email opens.
import { formatDate } from '@/lib/dates'
import { formatNumber, hostOf } from '@/lib/format'
import { rangeText, type ConversationMessage as Message, type LeadConversation, type StartupProfile } from '@/lib/queries/email-data'
import type { BestOffer, ConversationMessage, ConversationThread, EmailStatus, LeadExtras, PlanPageSummary, ProfileRow } from './types'

/** Where a fact or signal id came from, for the evidence links under each profile answer. */
export type SourceOf = Map<string, { url: string | null; at: string | null }>

const STEP = (step: number | null) => (step === null ? 'Reply' : step === 0 ? 'Day 1' : `Day ${step}`)
const THREAD_STATUS = new Set(['open', 'stopped', 'done'])

/** The drafted reply waiting for a person: our newest answer (no sequence step) still in draft or review. */
function pendingReply(messages: Message[]): Message | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]!
    if (m.direction === 'out' && m.step === null && (m.status === 'draft' || m.status === 'review') && m.body.trim()) return m
  }
  return null
}

/** The date a message shows: sent, received, or when it is due to go. */
const dateOf = (m: Message) =>
  m.direction === 'in' ? (m.createdAt ?? m.sentAt) : m.status === 'sent' ? (m.sentAt ?? m.updatedAt) : (m.scheduledFor ?? m.updatedAt ?? m.createdAt)

export function toThread(conv: LeadConversation, contactName: string | null): ConversationThread | null {
  const t = conv.thread
  if (!t) return null
  const pending = pendingReply(conv.messages)
  const messages: ConversationMessage[] = conv.messages
    .filter((m) => m.id !== pending?.id)
    .map((m) => ({
      id: m.id,
      direction: m.direction,
      step: m.step,
      subject: m.subject,
      body: m.body,
      status: m.status,
      at: dateOf(m),
      from: m.direction === 'in' ? contactName : null,
    }))
  return {
    id: t.id,
    toEmail: t.toEmail,
    status: THREAD_STATUS.has(t.status) ? (t.status as ConversationThread['status']) : 'open',
    stopReason: t.stopReason ? t.stopReason.replace(/_/g, ' ') : null,
    pausedUntil: t.pausedUntil,
    messages,
    suggestedReply: pending ? { messageId: pending.id, body: pending.body } : null,
  }
}

export function bestOffer(conv: LeadConversation): BestOffer | null {
  const o = [...conv.offers].sort((a, b) => a.rank - b.rank)[0]
  if (!o || !(o.promise || o.name)) return null
  const range = rangeText(o.range)
  return {
    name: o.name,
    text: o.promise ? (/[.!?]$/.test(o.promise) ? o.promise : `${o.promise}.`) : o.name,
    timeline: o.timeline ? `First version in ${o.timeline}${range ? ',' : '.'}` : null,
    range: range ? `${range}.` : null,
    why: o.whyNow,
  }
}

export function planPageOf(conv: LeadConversation, now: Date): PlanPageSummary | null {
  if (!conv.planPages.length) return null
  const last = conv.planPages.map((p) => p.lastViewedAt).filter((v): v is string => Boolean(v)).sort().at(-1) ?? null
  const live = conv.planPages.filter((p) => p.status === 'live')
  const note =
    conv.planViews === 0
      ? `Not viewed yet · shared ${conv.planPages[0]!.createdAt ? formatDate(conv.planPages[0]!.createdAt, now) : ''}`.replace(/ · shared $/, '')
      : conv.planPages.length > 1
        ? `${formatNumber(conv.planPages.length)} pages, ${formatNumber(live.length)} live`
        : null
  return { views: conv.planViews, lastViewedAt: last, url: null, note }
}

/** "Replied 16 Nov", "Day 3 sent 5 Nov, no reply yet", "Stopped: bounced". */
export function emailStatusOf(conv: LeadConversation, now: Date): EmailStatus | null {
  const t = conv.thread
  if (!t) return null
  const day = (v: string | null) => (v ? formatDate(v, now) : '')
  const lastIn = [...conv.messages].reverse().find((m) => m.direction === 'in')
  const lastSent = [...conv.messages].reverse().find((m) => m.direction === 'out' && m.status === 'sent')
  const failed = [...conv.messages].reverse().find((m) => m.direction === 'out' && m.status === 'failed')
  if (t.status === 'stopped') {
    const reason = (t.stopReason ?? '').replace(/_/g, ' ')
    const bad = /bounce|invalid|complain|unsubscrib/i.test(reason)
    if (lastIn && !bad) return { tone: 'ok', text: `Replied ${day(lastIn.createdAt)}${reason ? ` · stopped: ${reason}` : ''}` }
    return { tone: bad ? 'bad' : 'muted', text: reason ? `Stopped: ${reason}` : 'Stopped' }
  }
  if (lastIn) return { tone: 'ok', text: `Replied ${day(lastIn.createdAt)}` }
  if (failed && (!lastSent || (failed.updatedAt ?? '') > (lastSent.sentAt ?? ''))) return { tone: 'bad', text: `${STEP(failed.step)} failed to send` }
  if (t.status === 'done') return { tone: 'muted', text: 'Sequence finished, no reply' }
  if (lastSent) return { tone: 'muted', text: `${STEP(lastSent.step)} sent ${day(lastSent.sentAt)}, no reply yet` }
  return { tone: 'muted', text: 'Nothing sent yet' }
}

/**
 * The next email of the sequence and when it goes. The suggested reply is not counted: the page says "Approve
 * the suggested reply" itself while one waits, so an approval shows at once.
 */
export function nextEmailOf(conv: LeadConversation, now: Date): string | null {
  const t = conv.thread
  if (!t || t.status !== 'open') return null
  const pending = pendingReply(conv.messages)
  const next = conv.messages.find(
    (m) => m.id !== pending?.id && m.direction === 'out' && ['draft', 'review', 'approved', 'queued', 'sending'].includes(m.status),
  )
  if (!next) return null
  const when = next.scheduledFor ? ` ${formatDate(next.scheduledFor, now)}` : ''
  if (next.status === 'draft' || next.status === 'review') return `${STEP(next.step)} email waits for your review${when ? `, due${when}` : ''}.`
  return `${STEP(next.step)} email goes out${when ? ` on${when}` : ' with the next send'}.`
}

const TECH: Record<string, string> = { none: 'No tech team', lone_cto: 'One technical founder', has_engineers: 'Has engineers' }
const PAY: Record<string, string> = { yes: 'Yes', likely: 'Likely', no: 'No' }
const PRODUCT: Record<string, string> = {
  idea: 'An idea, nothing built',
  landing: 'A landing page',
  waitlist: 'A waitlist',
  no_code: 'Built on a no-code tool',
  web_app: 'A web app',
  mobile_app: 'A mobile app',
}

const usdShort = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(n % 1e6 ? 1 : 0)}M` : n >= 1e3 ? `$${Math.round(n / 1e3)}K` : `$${n}`)

/**
 * The startup profile's known answers, each with the plain "why" and the sources of the facts and signals it
 * rests on (0028). Unknown answers are left out: blank means unknown.
 */
export function profileRows(p: StartupProfile | null, sources: SourceOf, now: Date): ProfileRow[] {
  if (!p) return []
  const rows: ProfileRow[] = []
  const add = (key: string, label: string, value: string | null) => {
    if (!value) return
    const ev = p.evidence[key]
    const seen = new Set<string>()
    const links = (ev?.ids ?? [])
      .map((id) => sources.get(id))
      .filter((s): s is { url: string | null; at: string | null } => Boolean(s?.url))
      .filter((s) => (seen.has(s.url!) ? false : (seen.add(s.url!), true)))
      .slice(0, 2)
      .map((s) => ({ url: s.url!, host: hostOf(s.url), date: s.at ? formatDate(s.at, now) : '' }))
    rows.push({ key, label, value, why: ev?.why ?? null, sources: links })
  }
  add('tech_team', 'Tech team', TECH[p.techTeam] ?? null)
  add('team_size', 'Team size', p.teamSize !== null ? `${formatNumber(p.teamSize)} ${p.teamSize === 1 ? 'person' : 'people'}` : null)
  const product = PRODUCT[p.productStatus]
  add('product_status', 'Product today', product ? (p.productStatus === 'no_code' && p.noCodePlatform ? `Built on ${p.noCodePlatform}` : product) : null)
  const funding = [p.fundingUsd ? usdShort(p.fundingUsd) : null, p.fundingRound, p.fundingAt ? formatDate(p.fundingAt, now) : null].filter(Boolean).join(' · ')
  add('funding', 'Funding', funding || null)
  add('can_pay', 'Can pay', PAY[p.canPay] ?? null)
  add('uses_ai', 'Uses AI', p.usesAi === null ? null : p.usesAi ? 'Yes' : 'No')
  add('is_startup', 'Startup', p.isStartup === null ? null : p.isStartup ? 'Yes' : 'No')
  return rows
}

/** Everything the page passes to LeadScreen as `extras`, from one lead_conversation read. */
export function toLeadExtras(conv: LeadConversation | null, ctx: { contactName: string | null; sources: SourceOf; now: Date }): LeadExtras {
  if (!conv) return {}
  return {
    thread: toThread(conv, ctx.contactName),
    offer: bestOffer(conv),
    planPage: planPageOf(conv, ctx.now),
    profile: profileRows(conv.startupProfile, ctx.sources, ctx.now),
    emailStatus: emailStatusOf(conv, ctx.now),
    nextEmail: nextEmailOf(conv, ctx.now),
  }
}
