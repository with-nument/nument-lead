// The v2 lead page's view of lead_detail: plain, display-ready values, worked out on the server. Pure (no
// server or network access), so it is unit tested in tests/unit/lead-v2-model.test.ts.
import { factText, fieldLabel, scoreParts } from '@/components/lead/lead-sections'
import { stageLabel } from '@/components/ui2/stage-label'
import type { Json } from '@/lib/database.types'
import { formatDate, formatDateTime, relativeAge } from '@/lib/dates'
import { hostOf, safeUrl } from '@/lib/format'
import { canMarkReplied, lostReasonLabel, needsLostReason, type LeadMoney } from '@/lib/outcomes'
import { formatPhone } from '@/lib/phone'
import { CONTACT_SOURCE_LABEL, PHONE_TYPE_LABEL, countryLabel, pitchLabel, signalLabel } from '@/lib/signals'
import type { LeadDetail } from '@/lib/queries/page-data'
import type { Stage } from '@/lib/stages'
import type { DotTone } from '../../_ui/marks'

export type Evidence = { quote: string | null; text: string | null; url: string | null; host: string; date: string; expired: boolean }
export type EvidenceGroup = { label: string; items: Evidence[] }
export type FactView = { id: string; label: string; value: string; quote: string | null; url: string | null; host: string; verified: boolean }
export type PersonView = {
  id: string
  name: string | null
  initials: string
  role: string | null
  email: string | null
  phone: string | null
  phoneDisplay: string
  phoneType: string
  phoneTypeLabel: string
  sourceLabel: string
  sourceUrl: string | null
  sourceIsLinkedIn: boolean
  isDecisionMaker: boolean
  line: string
  lineWhy: string | null
  verified: boolean
  verifiedOn: string | null
  blocked: boolean
  blockReason: string | null
}
export type ActivityView = { id: string; text: string; note: string | null; at: string; when: string; ago: string; source: string }
export type MilestoneView = { label: string; date: string; strong?: boolean; faint?: boolean }

export type PrimaryKind = 'approve' | 'contacted' | 'replied' | 'stage' | 'brief'
export type PrimaryAction = { kind: PrimaryKind; label: string; to?: Stage; href?: string }

export type LeadView = {
  id: string
  name: string
  description: string | null
  place: string
  website: string | null
  host: string
  mapsUrl: string | null
  peopleCount: number
  segment: string
  grade: string | null
  total: number | null
  stage: string
  lostReason: string | null
  status: { tone: DotTone; text: string }
  notes: string | null
  nextStep: string | null
  dueAt: string | null
  dueLabel: string | null
  overdue: boolean
  ownerId: string | null
  added: string | null
  firstMessage: string | null
  evidence: EvidenceGroup[]
  angle: string | null
  judgeNote: string | null
  pitch: string
  testGroup: string | null
  parts: { label: string; value: number; max: number }[]
  facts: { title: string; items: FactView[] }[]
  people: PersonView[]
  message: string
  messageAlt: string
  emailSubject: string | null
  emailBody: string | null
  regenRequested: boolean
  needsEdit: boolean
  followups: { d3: string; d7: string; d3SentOn: string | null; d7SentOn: string | null }
  target: { phone: string | null; phoneType: string | null; email: string | null }
  milestones: MilestoneView[]
  activities: ActivityView[]
  pages: { id: string; url: string; title: string; host: string; read: string }[]
  money: LeadMoney | null
}

const UUIDISH = /^[0-9a-f-]{36}$/i
const obj = (v: Json | undefined) => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, Json | undefined>) : {})

export function initialsOf(name: string | null | undefined) {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  return ((parts[0]![0] ?? '') + (parts.length > 1 ? (parts[parts.length - 1]![0] ?? '') : '')).toUpperCase()
}

/** The one line under the header: where the lead is, as a dot and plain words. */
export function statusOf(lead: Pick<LeadDetail['lead'], 'stage' | 'wa_at' | 'meeting_at' | 'last_activity_at' | 'lost_reason'>, now: Date): { tone: DotTone; text: string } {
  const day = (v: string | null) => (v ? formatDate(v, now) : '')
  const ago = (v: string | null) => {
    if (!v) return ''
    const d = formatDate(v, now)
    const today = formatDate(now, now)
    return d === today ? 'today' : relativeAge(v, now)
  }
  switch (lead.stage) {
    case 'new':
      return { tone: 'none', text: 'Not contacted yet' }
    case 'contacted':
      return { tone: 'muted', text: lead.wa_at ? `Contacted ${day(lead.wa_at)}` : 'Contacted' }
    case 'talking':
      return { tone: 'ink', text: `Replied ${ago(lead.last_activity_at)}`.trim() }
    case 'discovery_booked':
      return { tone: 'ink', text: lead.meeting_at ? `Call ${formatDateTime(lead.meeting_at)}` : 'Call booked' }
    case 'discovery_done':
      return { tone: 'ink', text: 'Call done' }
    case 'proposal_sent':
      return { tone: 'warn', text: 'Proposal sent' }
    case 'won':
    case 'retainer':
      return { tone: 'ok', text: stageLabel(lead.stage) }
    default: {
      const reason = needsLostReason(lead.stage) ? lostReasonLabel(lead.lost_reason) : null
      return { tone: 'bad', text: reason ? `${stageLabel(lead.stage)} · ${reason}` : stageLabel(lead.stage) }
    }
  }
}

/**
 * The one solid button in the header, chosen by where the lead is. A reply waiting for approval wins over
 * everything; viewers and closed leads get none.
 */
export function primaryActionFor(input: { stage: string; canEdit: boolean; hasPendingReply: boolean }): PrimaryAction | null {
  if (!input.canEdit) return null
  if (input.hasPendingReply) return { kind: 'approve', label: 'Approve reply' }
  switch (input.stage) {
    case 'new':
      return { kind: 'contacted', label: 'Mark contacted' }
    case 'contacted':
      return canMarkReplied(input.stage) ? { kind: 'replied', label: 'Mark replied' } : null
    case 'talking':
      return { kind: 'stage', label: 'Call booked', to: 'discovery_booked' }
    case 'discovery_booked':
      return { kind: 'brief', label: 'Open brief', href: '/calls' }
    case 'discovery_done':
      return { kind: 'stage', label: 'Send proposal', to: 'proposal_sent' }
    case 'proposal_sent':
      return { kind: 'stage', label: 'Mark won', to: 'won' }
    default:
      return null
  }
}

/** A timeline entry as a sentence, in the v2 words for stages. */
export function activityText(a: { type: string; source: string; user_id: string | null; payload: Json }, names: Map<string, string>): string {
  const who = a.user_id ? (names.get(a.user_id) ?? 'A teammate') : a.source === 'engine' ? 'The engine' : a.source === 'sheet' ? 'The sheet' : 'Someone'
  const p = obj(a.payload)
  const str = (k: string) => (typeof p[k] === 'string' ? (p[k] as string) : '')
  switch (a.type) {
    case 'lead_created':
      return `Lead found${str('grade') ? `, grade ${str('grade')}` : ''}`
    case 'stage_change':
      return `${who} moved it from ${stageLabel(str('from'))} to ${stageLabel(str('to'))}`
    case 'grade_change':
      return `Grade changed from ${str('from') || 'none'} to ${str('to')}`
    case 'message_edited':
      return `${who} edited the message`
    case 'message_flagged':
      return 'The message checker asked for a human edit'
    case 'regen_request':
      return `${who} asked for a new message`
    case 'sent': {
      const ch = str('channel')
      const how = ch === 'web' ? ' on WhatsApp Web' : ch === 'app' ? ' on the WhatsApp app' : ch === 'call' ? ' by phone' : ch === 'email' ? ' by email' : ''
      return `${who} sent the first message${how}`
    }
    case 'followup_sent':
      return `${who} sent the day ${str('which') === 'd7' ? '7' : '3'} follow-up`
    case 'reply':
      return 'They replied'
    case 'call':
      return `${who} logged a call`
    case 'meeting':
      return `${who} logged a meeting`
    case 'proposal':
      return `${who} sent a proposal`
    case 'proposal_upload':
      return `${who} uploaded a proposal${str('file') ? ` (${str('file')})` : ''}`
    case 'note':
      return `${who} added a note`
    case 'edit': {
      const field = str('field')
      if (field === 'lost_reason') return `${who} gave the reason: ${(lostReasonLabel(str('reason')) ?? 'other').toLowerCase()}`
      const label = field === 'next_step' ? 'the next step' : field === 'owner' ? 'the owner' : field === 'deal_value' ? 'the deal value' : field.startsWith('followup') ? 'a follow-up' : 'the lead'
      return `${who} changed ${label}`
    }
    case 'feedback':
      return `${who} rated the lead ${Number(p.rating) > 0 ? 'good' : 'not good'}${str('reason') ? ` (${str('reason').toLowerCase()})` : ''}`
    case 'skip':
      return `${who} skipped it for 7 days`
    case 'wrong_contact':
      return `${who} marked the number as wrong`
    case 'undo':
      return `${who} undid the last change`
    case 'merge':
      return 'Merged with a duplicate'
    case 'won':
      return 'Marked as won'
    default:
      return `${who} ${a.type.replaceAll('_', ' ')}`
  }
}

const FACT_GROUPS: { title: string; fields: string[] }[] = [
  { title: 'Team', fields: ['decision_maker', 'team_member', 'staff_or_doctors', 'jsonld_employees', 'in_house_tech', 'tech_team'] },
  { title: 'Product', fields: ['product', 'product_status', 'service', 'price_point', 'jsonld_price_range', 'language'] },
  { title: 'Branches', fields: ['branches', 'locations_url'] },
  { title: 'Booking', fields: ['booking_method', 'whatsapp_present', 'chat_widget', 'contact_form_url'] },
  { title: 'Website and tech', fields: ['tech_stack', 'site_speed_mobile', 'website_status', 'is_agency_or_vendor'] },
  { title: 'Careers', fields: ['careers_role', 'careers_url', 'jsonld_job'] },
]

function factGroups(facts: LeadDetail['facts']) {
  const latest = new Map<string, LeadDetail['facts'][number]>()
  for (const f of facts) if (!latest.has(f.field)) latest.set(f.field, f)
  const view = (f: LeadDetail['facts'][number]): FactView => ({
    id: f.id,
    label: fieldLabel(f.field),
    value: factText(f.value) || 'Not stated',
    quote: f.quote,
    url: safeUrl(f.url),
    host: hostOf(f.url),
    verified: f.verified,
  })
  const used = new Set<string>()
  const groups = FACT_GROUPS.map((g) => ({
    title: g.title,
    items: g.fields.flatMap((field) => {
      const f = latest.get(field)
      if (!f) return []
      used.add(field)
      return [view(f)]
    }),
  }))
  const other = [...latest.values()].filter((f) => !used.has(f.field) && !/^jsonld_(phone|email)/.test(f.field) && f.field !== 'phone' && f.field !== 'email')
  if (other.length) groups.push({ title: 'Other', items: other.map(view) })
  return groups.filter((g) => g.items.length)
}

function isLinkedIn(url: string | null) {
  if (!url) return false
  try {
    return new URL(url).hostname.replace(/^www\./, '').endsWith('linkedin.com')
  } catch {
    return false
  }
}

// Who answers (15 Nov 2026): the owner's own line first, a front desk next, bots and call centres last.
const LINE_ORDER: Record<string, number> = { owner: 0, other: 1, front_desk: 2, bot: 3 }

export function toLeadView(
  detail: LeadDetail,
  ctx: { now: Date; isAdmin: boolean; names: Map<string, string>; segmentOf: (id: string | null) => string },
): LeadView {
  const { lead, business, contacts, signals, facts, score, activities, pages } = detail
  const now = ctx.now
  const blocked = new Set(detail.suppressedPhones)
  const website = safeUrl(business?.website ?? lead.website)
  const latestFact = (field: string) => facts.find((f) => f.field === field)
  const description = [latestFact('product'), latestFact('service')].map((f) => (f ? factText(f.value) : '')).find((t) => t.length > 0) ?? null

  const live = [...signals].sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at))
  const groups = new Map<string, Evidence[]>()
  for (const s of live) {
    const label = signalLabel(s.type)
    const list = groups.get(label) ?? []
    list.push({
      quote: s.quote,
      text: s.quote ? null : `${label} (+${Math.round(Number(s.points))})`,
      url: safeUrl(s.url),
      host: s.url ? hostOf(s.url) : s.source,
      date: formatDate(s.observed_at, now),
      expired: Date.parse(s.expires_at) <= now.getTime(),
    })
    groups.set(label, list)
  }
  if (!groups.size && (lead.top_signal_quote || lead.top_signal_type)) {
    groups.set(signalLabel(lead.top_signal_type), [
      {
        quote: lead.top_signal_quote,
        text: lead.top_signal_quote ? null : signalLabel(lead.top_signal_type),
        url: safeUrl(lead.top_signal_url),
        host: hostOf(lead.top_signal_url),
        date: lead.top_signal_at ? formatDate(lead.top_signal_at, now) : '',
        expired: false,
      },
    ])
  }

  const people: PersonView[] = [...contacts]
    .sort((a, b) => Number(b.is_decision_maker) - Number(a.is_decision_maker) || (LINE_ORDER[a.line ?? 'other'] ?? 1) - (LINE_ORDER[b.line ?? 'other'] ?? 1))
    .map((c) => {
      const listed = c.phone_e164 ? blocked.has(c.phone_e164) : false
      return {
        id: c.id,
        name: c.name,
        initials: initialsOf(c.name ?? c.email ?? '?'),
        role: c.role,
        email: c.email,
        phone: c.phone_e164,
        phoneDisplay: formatPhone(c.phone_e164),
        phoneType: c.phone_type,
        phoneTypeLabel: PHONE_TYPE_LABEL[c.phone_type] ?? 'Phone',
        sourceLabel: CONTACT_SOURCE_LABEL[c.source] ?? c.source,
        sourceUrl: safeUrl(c.source_url),
        sourceIsLinkedIn: isLinkedIn(c.source_url),
        isDecisionMaker: c.is_decision_maker,
        line: c.line ?? 'other',
        lineWhy: c.line_why ?? null,
        verified: c.verified,
        verifiedOn: c.verified && c.created_at ? formatDate(c.created_at, now) : null,
        blocked: c.do_not_contact || listed,
        blockReason: c.do_not_contact ? 'marked on the contact' : listed ? 'on the list' : null,
      }
    })

  const milestones: MilestoneView[] = []
  if (lead.wa_at) milestones.push({ label: 'First message sent', date: formatDate(lead.wa_at, now) })
  if (lead.d3_at) milestones.push({ label: 'Day 3 follow-up sent', date: formatDate(lead.d3_at, now) })
  if (lead.d7_at) milestones.push({ label: 'Day 7 follow-up sent', date: formatDate(lead.d7_at, now) })
  const reply = activities.find((a) => a.type === 'reply')
  if (reply) milestones.push({ label: 'They replied', date: formatDate(reply.at, now), strong: true })
  if (lead.meeting_at) milestones.push({ label: 'Call', date: formatDate(lead.meeting_at, now), strong: lead.stage === 'discovery_booked' })
  if (lead.wa_at && !lead.d3_at && lead.stage === 'contacted' && lead.followup_d3) milestones.push({ label: 'Day 3 follow-up next', date: '', faint: true })

  const parts = score ? scoreParts(score) : []
  const dueLabel = lead.due_at ? formatDate(lead.due_at, now) : null
  return {
    id: lead.id,
    name: lead.name,
    description,
    place: [lead.locality, lead.city, lead.country && lead.country.trim().toLowerCase() !== 'in' ? countryLabel(lead.country) : ''].filter(Boolean).join(', '),
    website,
    host: website ? hostOf(website) : (lead.web_domain ?? ''),
    mapsUrl: business?.place_id ? `https://www.google.com/maps/place/?q=place_id:${encodeURIComponent(business.place_id)}` : null,
    peopleCount: contacts.length,
    segment: ctx.segmentOf(lead.segment_id),
    grade: lead.grade,
    total: lead.total === null || lead.total === undefined ? null : Math.round(Number(lead.total)),
    stage: lead.stage,
    lostReason: lead.lost_reason,
    status: statusOf(lead, now),
    notes: lead.notes,
    nextStep: lead.next_step,
    dueAt: lead.due_at,
    dueLabel,
    overdue: Boolean(lead.due_at && Date.parse(`${lead.due_at}T23:59:59+05:30`) < now.getTime()),
    ownerId: lead.owner_id && UUIDISH.test(lead.owner_id) ? lead.owner_id : null,
    added: lead.created_at ? formatDate(lead.created_at, now) : null,
    firstMessage: lead.wa_at ? formatDate(lead.wa_at, now) : null,
    evidence: [...groups.entries()].map(([label, items]) => ({ label, items: items.slice(0, 3) })),
    angle: lead.angle,
    judgeNote: score?.judge_note ?? lead.judge_note,
    pitch: pitchLabel(lead.pitch_mode),
    testGroup: lead.test_group,
    parts,
    facts: factGroups(facts),
    people,
    message: lead.message ?? '',
    messageAlt: lead.message_alt ?? '',
    emailSubject: lead.email_subject,
    emailBody: lead.email_body,
    regenRequested: Boolean(lead.regen_requested_at),
    needsEdit: activities.some((a) => a.type === 'message_flagged') && !activities.some((a) => a.type === 'message_edited'),
    followups: {
      d3: lead.followup_d3 ?? '',
      d7: lead.followup_d7 ?? '',
      d3SentOn: lead.d3_at ? formatDate(lead.d3_at, now) : null,
      d7SentOn: lead.d7_at ? formatDate(lead.d7_at, now) : null,
    },
    target: { phone: lead.phone_e164, phoneType: lead.phone_type, email: lead.email },
    milestones,
    activities: activities.map((a) => {
      const p = obj(a.payload)
      return {
        id: a.id,
        text: activityText(a, ctx.names),
        note: a.type === 'note' && typeof p.text === 'string' ? p.text : null,
        at: a.at,
        when: formatDateTime(a.at),
        ago: relativeAge(a.at, now),
        source: a.source,
      }
    }),
    pages: pages.map((p) => ({ id: p.id, url: p.url, title: p.title || hostOf(p.url), host: hostOf(p.url), read: formatDate(p.fetched_at, now) })),
    money: ctx.isAdmin ? detail.money : null,
  }
}
