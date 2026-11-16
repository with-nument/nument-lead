import { describe, expect, it } from 'vitest'
import { bestOffer, emailStatusOf, nextEmailOf, planPageOf, profileRows, toLeadExtras, toThread, type SourceOf } from '@/app/(v2)/v2/leads/[id]/_lead/extras'
import { primaryActionFor } from '@/app/(v2)/v2/leads/[id]/_lead/model'
import { toLeadConversation, type LeadConversation } from '@/lib/queries/email-data'

const now = new Date('2026-11-16T03:30:00Z')
const thread = { id: 't1', status: 'open', stop_reason: null, mode: 'review', to_email: 'maya@leafline.in', paused_until: null, created_at: '2026-11-02T04:00:00Z' }
const out = (id: string, step: number | null, status: string, extra: Record<string, unknown> = {}) => ({
  id,
  thread_id: 't1',
  direction: 'out',
  step,
  subject: step === 0 ? 'Orders on WhatsApp' : null,
  body: `Body ${id}`,
  status,
  ...extra,
})

const conv = toLeadConversation({
  lead_id: 'l1',
  thread,
  threads: 1,
  messages: [
    out('m0', 0, 'sent', { sent_at: '2026-11-02T04:00:00Z' }),
    out('m3', 3, 'sent', { sent_at: '2026-11-05T04:00:00Z' }),
    { id: 'in1', thread_id: 't1', direction: 'in', step: null, body: 'Yes, open to a call.', status: 'received', created_at: '2026-11-16T02:42:00Z', suggested_reply: 'Hi Maya' },
    out('r1', null, 'review', { body: 'Hi Maya,\nThursday 6:30 pm?', created_at: '2026-11-16T02:45:00Z' }),
    out('m7', 7, 'cancelled', { scheduled_for: '2026-11-09T04:00:00Z' }),
  ],
  offers: [
    { rank: 2, key: 'retainer', name: 'Retainer', promise: 'A small team each month', timeline: 'ongoing', typical_range: { inr_month: [80000, 150000] } },
    { rank: 1, key: 'mvp', name: 'MVP sprint', promise: 'An ordering app for customers and a simple dashboard for the team', timeline: '6 weeks', typical_range: { inr: [200000, 300000] }, why_now: 'Orders break at 400 a week' },
  ],
  plan_pages: [
    { token: 'a'.repeat(22), kind: 'plan', status: 'live', views: 3, last_viewed_at: '2026-11-15T16:10:00Z', created_at: '2026-11-10T00:00:00Z' },
  ],
  startup_profile: {
    is_startup: true,
    team_size: 4,
    tech_team: 'none',
    can_pay: 'likely',
    product_status: 'no_code',
    no_code_platform: 'Shopify',
    uses_ai: null,
    funding_usd: 360000,
    funding_round: 'pre-seed',
    funding_at: '2026-10-28',
    evidence: {
      tech_team: { ids: ['f1', 's1', 'f1', 'missing'], why: 'Careers page asks for a product studio or a technical co-founder' },
      funding: { ids: ['s2'], why: null },
    },
  },
})!

const sources: SourceOf = new Map([
  ['f1', { url: 'https://leafline.in/careers', at: '2026-11-14T00:00:00Z' }],
  ['s1', { url: 'https://leafline.in/blog/year-one', at: '2026-10-02T00:00:00Z' }],
  ['s2', { url: 'https://leafline.in/press', at: '2026-10-28T00:00:00Z' }],
])

describe('Lead page extras from lead_conversation', () => {
  it('builds the thread without the waiting reply, which becomes the suggested reply', () => {
    const t = toThread(conv, 'Maya Rao')!
    expect(t.suggestedReply).toEqual({ messageId: 'r1', body: 'Hi Maya,\nThursday 6:30 pm?' })
    expect(t.messages.map((m) => m.id)).toEqual(['m0', 'm3', 'in1', 'm7'])
    expect(t.messages[2]).toMatchObject({ direction: 'in', from: 'Maya Rao', at: '2026-11-16T02:42:00Z' })
    expect(t.messages[0]).toMatchObject({ status: 'sent', at: '2026-11-02T04:00:00Z' })
    expect(t.messages[3]).toMatchObject({ status: 'cancelled', at: '2026-11-09T04:00:00Z' })
    expect(t.toEmail).toBe('maya@leafline.in')
    // The header's one button becomes Approve reply while it waits.
    expect(primaryActionFor({ stage: 'talking', canEdit: true, hasPendingReply: Boolean(t.suggestedReply) })?.label).toBe('Approve reply')
  })

  it('has no thread (and no suggested reply) before any email', () => {
    const none = toLeadConversation({ lead_id: 'l2', thread: null, messages: [] })!
    expect(toThread(none, null)).toBeNull()
    expect(emailStatusOf(none, now)).toBeNull()
    expect(nextEmailOf(none, now)).toBeNull()
    expect(toLeadExtras(null, { contactName: null, sources, now })).toEqual({})
  })

  it('picks the rank 1 offer with its timeline and range', () => {
    expect(bestOffer(conv)).toEqual({
      name: 'MVP sprint',
      text: 'An ordering app for customers and a simple dashboard for the team.',
      timeline: 'First version in 6 weeks,',
      range: '₹2L to ₹3L.',
      why: 'Orders break at 400 a week',
    })
  })

  it('counts plan page views, never opens', () => {
    expect(planPageOf(conv, now)).toEqual({ views: 3, lastViewedAt: '2026-11-15T16:10:00Z', url: null, note: null })
    const unseen: LeadConversation = { ...conv, planViews: 0, planPages: [{ ...conv.planPages[0]!, views: 0, lastViewedAt: null }] }
    expect(planPageOf(unseen, now)?.note).toBe('Not viewed yet · shared 10 Nov')
  })

  it('says where the email sequence stands and what comes next', () => {
    expect(emailStatusOf(conv, now)).toEqual({ tone: 'ok', text: 'Replied 16 Nov' })
    const waiting: LeadConversation = { ...conv, messages: conv.messages.filter((m) => m.direction === 'out' && m.step !== null) }
    expect(emailStatusOf(waiting, now)).toEqual({ tone: 'muted', text: 'Day 3 sent 5 Nov, no reply yet' })
    const bounced: LeadConversation = { ...conv, thread: { ...conv.thread!, status: 'stopped', stopReason: 'hard_bounce' } }
    expect(emailStatusOf(bounced, now)).toEqual({ tone: 'bad', text: 'Stopped: hard bounce' })
    // The suggested reply is the page's own line; the sequence's next email is this one.
    expect(nextEmailOf(conv, now)).toBeNull()
    const queued: LeadConversation = {
      ...waiting,
      messages: [...waiting.messages, { ...waiting.messages[0]!, id: 'm12', step: 12, status: 'queued', scheduledFor: '2026-11-18T04:00:00Z', sentAt: null }],
    }
    expect(nextEmailOf(queued, now)).toBe('Day 12 email goes out on 18 Nov.')
  })

  it('lists the known startup profile answers with their why and deduplicated sources', () => {
    const rows = profileRows(conv.startupProfile, sources, now)
    expect(rows.map((r) => [r.label, r.value])).toEqual([
      ['Tech team', 'No tech team'],
      ['Team size', '4 people'],
      ['Product today', 'Built on Shopify'],
      ['Funding', '$360K · pre-seed · 28 Oct'],
      ['Can pay', 'Likely'],
      ['Startup', 'Yes'],
    ])
    expect(rows[0]!.why).toBe('Careers page asks for a product studio or a technical co-founder')
    expect(rows[0]!.sources).toEqual([
      { url: 'https://leafline.in/careers', host: 'leafline.in', date: '14 Nov' },
      { url: 'https://leafline.in/blog/year-one', host: 'leafline.in', date: '2 Oct' },
    ])
    expect(rows[3]!.sources.map((s) => s.url)).toEqual(['https://leafline.in/press'])
    expect(profileRows(null, sources, now)).toEqual([])
  })
})
