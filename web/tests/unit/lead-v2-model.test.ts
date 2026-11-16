import { describe, expect, it } from 'vitest'
import { toBoardView } from '@/app/(v2)/v2/deals/_board/model'
import { activityText, primaryActionFor, statusOf, toLeadView } from '@/app/(v2)/v2/leads/[id]/_lead/model'
import { contactOf, extraFilterCount, scopeFilters, scopeOf } from '@/app/(v2)/v2/leads/_list/model'
import { MOCK_NOW, mockBoard, mockLeadDetail } from '@/app/(v2)/v2/kit/w2/mock'
import { EMPTY_FILTERS } from '@/lib/leads-filters'

const ctx = { now: MOCK_NOW, isAdmin: true, names: new Map<string, string>(), segmentOf: () => 'Startups' }

describe('the lead page header action', () => {
  it('is one action, chosen by where the lead is', () => {
    const at = (stage: string, hasPendingReply = false) => primaryActionFor({ stage, canEdit: true, hasPendingReply })?.label ?? null
    expect(at('new')).toBe('Mark contacted')
    expect(at('contacted')).toBe('Mark replied')
    expect(at('talking')).toBe('Call booked')
    expect(at('discovery_booked')).toBe('Open brief')
    expect(at('discovery_done')).toBe('Send proposal')
    expect(at('proposal_sent')).toBe('Mark won')
    expect(at('lost')).toBeNull()
    expect(at('won')).toBeNull()
  })

  it('puts a waiting reply first and gives viewers nothing', () => {
    expect(primaryActionFor({ stage: 'contacted', canEdit: true, hasPendingReply: true })?.kind).toBe('approve')
    expect(primaryActionFor({ stage: 'new', canEdit: false, hasPendingReply: true })).toBeNull()
  })
})

describe('the lead view', () => {
  const view = toLeadView(mockLeadDetail, ctx)

  it('groups dated evidence by signal and keeps every source', () => {
    expect(view.evidence.map((g) => g.label)).toEqual(['Asked for help publicly', 'Raised funding'])
    expect(view.evidence[0]!.items).toHaveLength(2)
    expect(view.evidence[0]!.items.every((e) => e.url && e.date)).toBe(true)
  })

  it('reads the description, people and milestones from the data, never invents them', () => {
    expect(view.description).toContain('Plant-care subscriptions')
    expect(view.peopleCount).toBe(2)
    expect(view.people[0]!.name).toBe('Maya Rao')
    expect(view.people[0]!.verifiedOn).toBeTruthy()
    expect(view.milestones.map((m) => m.label)).toEqual(['First message sent', 'Day 3 follow-up sent', 'Day 7 follow-up sent', 'They replied'])
    expect(view.status).toEqual({ tone: 'ink', text: 'Replied today' })
  })

  it('shows money to admins only', () => {
    expect(view.money?.deal).toBe(250000)
    expect(toLeadView(mockLeadDetail, { ...ctx, isAdmin: false }).money).toBeNull()
  })

  it('says closed stages with their reason', () => {
    expect(statusOf({ stage: 'lost', wa_at: null, meeting_at: null, last_activity_at: null, lost_reason: 'price' }, MOCK_NOW)).toEqual({ tone: 'bad', text: 'Lost · Price' })
    expect(statusOf({ stage: 'new', wa_at: null, meeting_at: null, last_activity_at: null, lost_reason: null }, MOCK_NOW).text).toBe('Not contacted yet')
  })

  it('writes the timeline in the v2 stage words', () => {
    expect(activityText({ type: 'stage_change', source: 'app', user_id: null, payload: { from: 'contacted', to: 'talking' } }, new Map())).toBe('Someone moved it from Contacted to Replied')
  })
})

describe('the Leads list', () => {
  it('maps every scope tab to filters and back', () => {
    for (const s of ['all', 'new', 'a', 'replied', 'not_contacted'] as const) expect(scopeOf(scopeFilters(s, 'pune', MOCK_NOW), MOCK_NOW)).toBe(s)
    expect(scopeFilters('new', '', MOCK_NOW).from).toBe('2026-11-15')
    expect(scopeOf({ ...EMPTY_FILTERS, grade: ['A', 'B'] }, MOCK_NOW)).toBeNull()
    expect(extraFilterCount({ ...EMPTY_FILTERS, grade: ['A', 'B'], mobile: true })).toBe(2)
  })

  it('only counts a published number as a contact', () => {
    expect(contactOf({ phone_e164: '+919800000000', phone_type: 'mobile', contact_name: null }).text).toBe('Mobile published')
    expect(contactOf({ phone_e164: null, phone_type: null, contact_name: 'A' }).tone).toBe('warn')
    expect(contactOf({ phone_e164: null, phone_type: null, contact_name: null }).tone).toBe('none')
  })
})

describe('the Deals board', () => {
  it('has the open stages as columns, closed folded with counts, and one next step', () => {
    const v = toBoardView(mockBoard, { now: MOCK_NOW, isAdmin: true })
    expect(v.columns.map((c) => c.label)).toEqual(['Contacted', 'Replied', 'Call booked', 'Call done', 'Proposal'])
    expect(v.columns[0]!.count).toBe(38)
    expect(v.closed.map((c) => [c.stage, c.count])).toEqual([
      ['won', 3],
      ['lost', 11],
      ['not_now', 6],
    ])
    expect(v.openCount).toBe(56)
    expect(v.primary?.label).toBe('Send Orbit Kitchen proposal')
    expect(v.inPlay).toBeTruthy()
  })

  it('never shows money to callers', () => {
    const v = toBoardView(mockBoard, { now: MOCK_NOW, isAdmin: false })
    expect(v.inPlay).toBeNull()
    expect(v.columns.every((c) => c.total === null)).toBe(true)
  })
})
