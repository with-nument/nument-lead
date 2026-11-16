// What the email functions return (supabase/migrations/0033_inbox_calls.sql), as types, and the conversions
// from their JSON. Pure: no server or network access, so it is unit tested and shared by every page. The
// functions run as the signed-in user, so Row Level Security has already decided every row (viewers get no email).
import type { Json } from '@/lib/database.types'
import { addDays, formatDate, formatTime, istDate } from '@/lib/dates'

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : {})
const objOrNull = (v: unknown): Obj | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : null)
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const str = (v: unknown): string | null => (typeof v === 'string' ? v : v === null || v === undefined ? null : String(v))
const text = (v: unknown): string => str(v) ?? ''
const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}
const count = (v: unknown): number => num(v) ?? 0
const strings = (v: unknown): string[] => list(v).map(text).filter(Boolean)

/** A list time in India time: "8:12 am" today, "Yesterday", "Tomorrow", else "12 Nov". */
export function shortWhen(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ''
  const day = istDate(iso)
  const today = istDate(now)
  if (day === today) return formatTime(iso)
  if (day === addDays(today, -1)) return 'Yesterday'
  if (day === addDays(today, 1)) return 'Tomorrow'
  return formatDate(iso, now)
}

/* ------------------------------------------------------------------------------------------------------------
 * Messages
 * ---------------------------------------------------------------------------------------------------------- */

/** An outgoing message's status (0022). Only draft, review and approved can still be changed by a person. */
export type MessageStatus = 'draft' | 'review' | 'approved' | 'queued' | 'sending' | 'sent' | 'failed' | 'cancelled' | 'received'
const STATUSES: readonly MessageStatus[] = ['draft', 'review', 'approved', 'queued', 'sending', 'sent', 'failed', 'cancelled', 'received']
const status = (v: unknown): MessageStatus => (STATUSES.includes(v as MessageStatus) ? (v as MessageStatus) : 'draft')

/** The engine's reading of a reply (classify_reply). */
export type ReplyClass = 'interested' | 'send_plan' | 'question' | 'not_now' | 'out_of_office' | 'wrong_person' | 'unsubscribe' | 'other'

export const REPLY_LABEL: Record<string, string> = {
  interested: 'Interested',
  send_plan: 'Wants the plan',
  question: 'Question',
  not_now: 'Later',
  out_of_office: 'Away',
  wrong_person: 'Wrong person',
  unsubscribe: 'Unsubscribed',
  other: 'Other',
}

/** "Day 0" for a sequence step, "Reply" for an answer we wrote. */
export const stepLabel = (step: number | null) => (step === null ? 'Reply' : `Day ${step}`)

/** True while a person may still approve, edit or cancel it (the 0022 policy). */
export const isEditable = (s: MessageStatus) => s === 'draft' || s === 'review' || s === 'approved'

export type InboundMessage = {
  id: string
  subject: string | null
  body: string
  at: string | null
  classification: string | null
  confidence: number | null
  suggestedReply: string | null
}

export type DraftMessage = {
  id: string
  step: number | null
  subject: string | null
  body: string
  status: MessageStatus
  scheduledFor: string | null
  sentAt: string | null
  updatedAt: string | null
  error: string | null
}

export type SentMessage = { id: string; step: number | null; subject: string | null; body: string; at: string | null }

const inbound = (v: unknown): InboundMessage | null => {
  const o = objOrNull(v)
  if (!o) return null
  return {
    id: text(o.id),
    subject: str(o.subject),
    body: text(o.body),
    at: str(o.at),
    classification: str(o.classification),
    confidence: num(o.confidence),
    suggestedReply: str(o.suggested_reply),
  }
}

const draft = (v: unknown): DraftMessage | null => {
  const o = objOrNull(v)
  if (!o) return null
  return {
    id: text(o.id),
    step: num(o.step),
    subject: str(o.subject),
    body: text(o.body),
    status: status(o.status),
    scheduledFor: str(o.scheduled_for),
    sentAt: str(o.sent_at),
    updatedAt: str(o.updated_at),
    error: str(o.error),
  }
}

const sent = (v: unknown): SentMessage | null => {
  const o = objOrNull(v)
  if (!o) return null
  return { id: text(o.id), step: num(o.step), subject: str(o.subject), body: text(o.body), at: str(o.at) }
}

/* ------------------------------------------------------------------------------------------------------------
 * Inbox: inbox_page(tab, cursor_at, cursor_id, page_size)
 * ---------------------------------------------------------------------------------------------------------- */

export type InboxTab = 'replies' | 'review' | 'done'
export const INBOX_TABS: readonly InboxTab[] = ['replies', 'review', 'done']
export const isInboxTab = (v: unknown): v is InboxTab => INBOX_TABS.includes(v as InboxTab)

export type InboxCounts = Record<InboxTab, number>
export type InboxCursor = { at: string; id: string }

export type InboxItem = {
  /** The message the item is about: the answer (replies) or the outgoing email (review, done). */
  key: string
  tab: InboxTab
  at: string | null
  threadId: string
  threadStatus: string | null
  leadId: string
  company: string
  city: string | null
  country: string | null
  grade: string | null
  stage: string | null
  contactName: string | null
  contactRole: string | null
  toEmail: string | null
  inbound: InboundMessage | null
  /** The email waiting for a person (replies, review) or the one dealt with (done). */
  draft: DraftMessage | null
  /** Our last email before the answer, for context. */
  lastOut: SentMessage | null
}

export type InboxPage = { tab: InboxTab; counts: InboxCounts; items: InboxItem[]; nextCursor: InboxCursor | null }

export function toInboxItem(v: unknown): InboxItem {
  const o = obj(v)
  return {
    key: text(o.key),
    tab: isInboxTab(o.tab) ? o.tab : 'replies',
    at: str(o.at),
    threadId: text(o.thread_id),
    threadStatus: str(o.thread_status),
    leadId: text(o.lead_id),
    company: text(o.company),
    city: str(o.city),
    country: str(o.country),
    grade: str(o.grade),
    stage: str(o.stage),
    contactName: str(o.contact_name),
    contactRole: str(o.contact_role),
    toEmail: str(o.to_email),
    inbound: inbound(o.inbound),
    draft: draft(o.draft),
    lastOut: sent(o.last_out),
  }
}

export function toInboxPage(data: Json | null): InboxPage {
  const d = obj(data)
  const c = obj(d.counts)
  const next = objOrNull(d.next_cursor)
  return {
    tab: isInboxTab(d.tab) ? d.tab : 'replies',
    counts: { replies: count(c.replies), review: count(c.review), done: count(c.done) },
    items: list(d.items).map(toInboxItem),
    nextCursor: next && str(next.at) && str(next.id) ? { at: text(next.at), id: text(next.id) } : null,
  }
}

/** For Today: how many replies and drafts wait, and the newest replies. */
export type InboxSummary = { counts: InboxCounts; replies: InboxItem[] }

/* ------------------------------------------------------------------------------------------------------------
 * Calls: calls_page()
 * ---------------------------------------------------------------------------------------------------------- */

export type BriefSection = { title: string; text: string; points: string[] }

/** The pre-call brief the engine writes (models.PrecallBrief), as the 'brief' activity stores it. */
export type PrecallBrief = {
  summary: string
  whyNow: string
  whatTheyNeed: string[]
  questions: string[]
  offerKey: string | null
  risks: string[]
}

export const toPrecallBrief = (v: unknown): PrecallBrief | null => {
  const o = objOrNull(v)
  if (!o) return null
  return {
    summary: text(o.summary),
    whyNow: text(o.why_now),
    whatTheyNeed: strings(o.what_they_need),
    questions: strings(o.questions),
    offerKey: str(o.offer_key),
    risks: strings(o.risks),
  }
}

export type Booking = {
  kind: string | null
  start: string | null
  end: string | null
  location: string | null
  notes: string | null
  at: string | null
}

const booking = (v: unknown): Booking | null => {
  const o = objOrNull(v)
  if (!o) return null
  return { kind: str(o.kind), start: str(o.start), end: str(o.end), location: str(o.location), notes: str(o.notes), at: str(o.at) }
}

/** Typical price range of an offer (0021): {"inr": [lo, hi]} or monthly {"inr_month": [lo, hi]}. */
export type OfferRange = { inr: [number, number] | null; usd: [number, number] | null; monthly: boolean }

const pair = (v: unknown): [number, number] | null => {
  const [lo, hi, ...rest] = list(v).map(num)
  return rest.length === 0 && lo != null && hi != null ? [lo, hi] : null
}

const offerRange = (v: unknown): OfferRange => {
  const o = obj(v)
  const monthly = 'inr_month' in o || 'usd_month' in o
  return { inr: pair(monthly ? o.inr_month : o.inr), usd: pair(monthly ? o.usd_month : o.usd), monthly }
}

/** ₹2.5L, ₹80K, ₹1.2Cr: short rupee amounts for an offer's typical range. */
export function inrShort(n: number) {
  const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1).replace(/\.0$/, ''))
  if (n >= 1e7) return `₹${fmt(n / 1e7)}Cr`
  if (n >= 1e5) return `₹${fmt(n / 1e5)}L`
  if (n >= 1e3) return `₹${fmt(n / 1e3)}K`
  return `₹${n}`
}

/** "₹1.5L to ₹6L", "₹20K to ₹80K a month", or the dollar range when no rupee one is known. */
export function rangeText(r: OfferRange) {
  const month = r.monthly ? ' a month' : ''
  if (r.inr) return `${inrShort(r.inr[0])} to ${inrShort(r.inr[1])}${month}`
  if (r.usd) return `$${r.usd[0].toLocaleString('en-US')} to $${r.usd[1].toLocaleString('en-US')}${month}`
  return ''
}

export type LeadOffer = {
  rank: number
  key: string
  name: string
  promise: string
  timeline: string
  range: OfferRange
  whyNow: string | null
}

const offer = (v: unknown, rank = 1): LeadOffer | null => {
  const o = objOrNull(v)
  if (!o) return null
  return {
    rank: num(o.rank) ?? rank,
    key: text(o.key),
    name: text(o.name),
    promise: text(o.promise),
    timeline: text(o.timeline),
    range: offerRange(o.typical_range),
    whyNow: str(o.why_now),
  }
}

export type PlanViews = { views: number; firstViewedAt: string | null; lastViewedAt: string | null }

export type CallProposal = { id: string; status: string; callNotes: string | null; drafted: boolean; updatedAt: string | null }

export type Call = {
  leadId: string
  meetingAt: string
  company: string
  website: string | null
  city: string | null
  country: string | null
  grade: string | null
  stage: string | null
  contactName: string | null
  contactRole: string | null
  email: string | null
  booking: Booking | null
  brief: { at: string | null; content: PrecallBrief | null } | null
  offer: LeadOffer | null
  plan: PlanViews | null
  proposal: CallProposal | null
}

export function toCall(v: unknown): Call {
  const o = obj(v)
  const b = objOrNull(o.brief)
  const p = objOrNull(o.plan)
  const pr = objOrNull(o.proposal)
  return {
    leadId: text(o.lead_id),
    meetingAt: text(o.meeting_at),
    company: text(o.company),
    website: str(o.website),
    city: str(o.city),
    country: str(o.country),
    grade: str(o.grade),
    stage: str(o.stage),
    contactName: str(o.contact_name),
    contactRole: str(o.contact_role),
    email: str(o.email),
    booking: booking(o.booking),
    brief: b ? { at: str(b.at), content: toPrecallBrief(b.content) } : null,
    offer: offer(o.offer),
    plan: p ? { views: count(p.views), firstViewedAt: str(p.first_viewed_at), lastViewedAt: str(p.last_viewed_at) } : null,
    proposal: pr
      ? { id: text(pr.id), status: text(pr.status), callNotes: str(pr.call_notes), drafted: pr.drafted === true, updatedAt: str(pr.updated_at) }
      : null,
  }
}

export type CallsPage = { today: Call[]; upcoming: Call[]; earlier: Call[] }

export function toCallsPage(data: Json | null): CallsPage {
  const d = obj(data)
  return { today: list(d.today).map(toCall), upcoming: list(d.upcoming).map(toCall), earlier: list(d.earlier).map(toCall) }
}

/* ------------------------------------------------------------------------------------------------------------
 * A lead's conversation: lead_conversation(lead_id)
 * ---------------------------------------------------------------------------------------------------------- */

export type ConversationMessage = {
  id: string
  threadId: string
  direction: 'out' | 'in'
  step: number | null
  subject: string | null
  body: string
  status: MessageStatus
  scheduledFor: string | null
  sentAt: string | null
  classification: string | null
  confidence: number | null
  suggestedReply: string | null
  error: string | null
  createdAt: string | null
  updatedAt: string | null
}

export type EmailThread = {
  id: string
  status: string
  stopReason: string | null
  mode: string
  toEmail: string
  pausedUntil: string | null
  createdAt: string | null
}

export type PlanPage = {
  token: string
  kind: 'plan' | 'proposal'
  status: string
  views: number
  firstViewedAt: string | null
  lastViewedAt: string | null
  createdAt: string | null
  expiresAt: string | null
}

/** One answer of the startup profile with the evidence behind it (0028). */
export type ProfileEvidence = { ids: string[]; why: string | null }

export type StartupProfile = {
  isStartup: boolean | null
  teamSize: number | null
  techTeam: string
  canPay: string
  productStatus: string
  noCodePlatform: string | null
  usesAi: boolean | null
  fundingUsd: number | null
  fundingRound: string | null
  fundingAt: string | null
  checkedAt: string | null
  evidence: Record<string, ProfileEvidence>
}

export type Proposal = {
  id: string
  status: string
  callNotes: string | null
  content: Json
  planToken: string | null
  createdAt: string | null
  updatedAt: string | null
}

export type LeadConversation = {
  leadId: string
  meetingAt: string | null
  thread: EmailThread | null
  threads: number
  messages: ConversationMessage[]
  offers: LeadOffer[]
  planPages: PlanPage[]
  /** Views of every plan page together (no email opens: the app does not track them). */
  planViews: number
  startupProfile: StartupProfile | null
  briefs: { at: string | null; meetingAt: string | null; content: PrecallBrief | null }[]
  bookings: Booking[]
  proposals: Proposal[]
}

const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null)

const profile = (v: unknown): StartupProfile | null => {
  const o = objOrNull(v)
  if (!o) return null
  const ev = obj(o.evidence)
  return {
    isStartup: bool(o.is_startup),
    teamSize: num(o.team_size),
    techTeam: text(o.tech_team) || 'unknown',
    canPay: text(o.can_pay) || 'unknown',
    productStatus: text(o.product_status) || 'unknown',
    noCodePlatform: str(o.no_code_platform),
    usesAi: bool(o.uses_ai),
    fundingUsd: num(o.funding_usd),
    fundingRound: str(o.funding_round),
    fundingAt: str(o.funding_at),
    checkedAt: str(o.checked_at),
    evidence: Object.fromEntries(Object.entries(ev).map(([k, e]) => [k, { ids: strings(obj(e).ids), why: str(obj(e).why) }])),
  }
}

export function toLeadConversation(data: Json | null): LeadConversation | null {
  const d = objOrNull(data)
  if (!d) return null
  const t = objOrNull(d.thread)
  const planPages: PlanPage[] = list(d.plan_pages).map((v) => {
    const p = obj(v)
    return {
      token: text(p.token),
      kind: p.kind === 'proposal' ? 'proposal' : 'plan',
      status: text(p.status),
      views: count(p.views),
      firstViewedAt: str(p.first_viewed_at),
      lastViewedAt: str(p.last_viewed_at),
      createdAt: str(p.created_at),
      expiresAt: str(p.expires_at),
    }
  })
  return {
    leadId: text(d.lead_id),
    meetingAt: str(d.meeting_at),
    thread: t
      ? {
          id: text(t.id),
          status: text(t.status),
          stopReason: str(t.stop_reason),
          mode: text(t.mode),
          toEmail: text(t.to_email),
          pausedUntil: str(t.paused_until),
          createdAt: str(t.created_at),
        }
      : null,
    threads: count(d.threads),
    messages: list(d.messages).map((v) => {
      const m = obj(v)
      return {
        id: text(m.id),
        threadId: text(m.thread_id),
        direction: m.direction === 'in' ? 'in' : 'out',
        step: num(m.step),
        subject: str(m.subject),
        body: text(m.body),
        status: status(m.status),
        scheduledFor: str(m.scheduled_for),
        sentAt: str(m.sent_at),
        classification: str(m.classification),
        confidence: num(m.confidence),
        suggestedReply: str(m.suggested_reply),
        error: str(m.error),
        createdAt: str(m.created_at),
        updatedAt: str(m.updated_at),
      }
    }),
    offers: list(d.offers)
      .map((v, i) => offer(v, i + 1))
      .filter((o): o is LeadOffer => o !== null),
    planPages,
    planViews: planPages.reduce((s, p) => s + p.views, 0),
    startupProfile: profile(d.startup_profile),
    briefs: list(d.briefs).map((v) => {
      const b = obj(v)
      return { at: str(b.at), meetingAt: str(b.meeting_at), content: toPrecallBrief(b.content) }
    }),
    bookings: list(d.bookings)
      .map(booking)
      .filter((b): b is Booking => b !== null),
    proposals: list(d.proposals).map((v) => {
      const p = obj(v)
      return {
        id: text(p.id),
        status: text(p.status),
        callNotes: str(p.call_notes),
        content: (p.content ?? {}) as Json,
        planToken: str(p.plan_token),
        createdAt: str(p.created_at),
        updatedAt: str(p.updated_at),
      }
    }),
  }
}
