import { describe, expect, it } from 'vitest'
import { EMPTY_FILTERS } from '@/lib/leads-filters'
import {
  amount,
  boardFiltersJson,
  capOf,
  leadsFiltersJson,
  toBoard,
  toEngineLive,
  toHomeSummary,
  toInsights,
  toLeadDetail,
  toLeadsPage,
  toNavCounts,
  toSearchResults,
} from '@/lib/queries/page-data'

// The JSON below is shaped like what the functions in supabase/migrations/0024_page_reads.sql return
// (engine/tests/test_page_reads.py checks the functions themselves against the database).
const A = '00000000-0000-4000-8000-000000000001'
const B = '00000000-0000-4000-8000-000000000002'

describe('amount and capOf', () => {
  it('reads numbers and numeric strings, and nothing else', () => {
    expect(amount(150000)).toBe(150000)
    expect(amount('2500.50')).toBe(2500.5)
    expect(amount(null)).toBeNull()
    expect(amount(undefined)).toBeNull()
    expect(amount('')).toBeNull()
    expect(amount('lots')).toBeNull()
  })

  it('uses 750 rupees unless the cap is a positive number', () => {
    expect(capOf(900)).toBe(900)
    expect(capOf('1200')).toBe(1200)
    expect(capOf(0)).toBe(750)
    expect(capOf(null)).toBe(750)
    expect(capOf({ value: 5 })).toBe(750)
  })
})

describe('toHomeSummary', () => {
  const json = {
    counts: { ready: 12, contacted_this_week: 30, talking: 4, discovery: 2, proposals: 1, overdue: 3 },
    won_this_month_inr: 250000.5,
    send: [{ lead_id: A, company: 'Smile Dental', grade: 'A', phone_e164: '+919800000001' }],
    followups: [
      { lead_id: B, company: 'Lotus Clinic', which: 'd3', due_on: '2026-11-15', city: 'Pune', phone_type: 'mobile' },
      { lead_id: B, company: 'Lotus Clinic', which: 'd12', due_on: '2026-11-15' },
    ],
  }

  it('turns the counts into the KPI tiles', () => {
    expect(toHomeSummary(json).kpis).toEqual({
      ready: 12,
      contactedThisWeek: 30,
      talking: 4,
      discovery: 2,
      proposals: 1,
      overdue: 3,
      wonThisMonthInr: 250000.5,
    })
  })

  it('keeps the money empty for everyone but admins', () => {
    expect(toHomeSummary({ ...json, won_this_month_inr: null }).kpis.wonThisMonthInr).toBeNull()
  })

  it('passes the rows through, keeping only day 3 and day 7 follow-ups', () => {
    const s = toHomeSummary(json)
    expect(s.send).toEqual(json.send)
    expect(s.followups.map((f) => f.which)).toEqual(['d3'])
    expect(s.followups[0]).toMatchObject({ city: 'Pune', phone_type: 'mobile' })
  })

  it('survives an empty answer', () => {
    expect(toHomeSummary(null)).toEqual({
      kpis: { ready: 0, contactedThisWeek: 0, talking: 0, discovery: 0, proposals: 0, overdue: 0, wonThisMonthInr: null },
      send: [],
      followups: [],
    })
  })
})

describe('toNavCounts', () => {
  it('maps the counts', () => {
    expect(toNavCounts({ ready: 5, followups_due: 2, overdue: 1, deals: 7, inbox_new: 0 })).toEqual({
      ready: 5,
      followupsDue: 2,
      overdue: 1,
      deals: 7,
      inboxNew: 0,
    })
    expect(toNavCounts(null).deals).toBe(0)
  })
})

describe('toLeadDetail', () => {
  const lead = { id: A, business_id: B, name: 'Smile Dental', stage: 'lost', lost_reason: 'price', total: 78 }
  const json = {
    lead,
    business: { name: 'Smile Dental', website: 'https://smile.example.com', place_id: null },
    contacts: [{ id: 'c1', name: 'Dr. Rao', phone_e164: '+919800000001', line: 'owner' }],
    suppressed_phones: ['+919800000001', 42],
    signals: [{ id: 's1', type: 'hiring_frontdesk', points: 8 }],
    facts: [{ id: 'f1', field: 'staff', value: 5, verified: true }],
    score: { total: 78, grade: 'A', reasons: {} },
    pages: [{ id: 'p1', url: 'https://smile.example.com', title: 'Home', fetched_at: '2026-11-14T00:00:00Z' }],
    activities: [{ id: 'a1', type: 'note', source: 'app', at: '2026-11-14T00:00:00Z', user_id: null, payload: {} }],
    feedback: [],
    money: { deal: 150000, retainer: '1500', currency: 'USD' },
  }

  it('keeps every part of the lead page', () => {
    const d = toLeadDetail(json)!
    expect(d.lead).toMatchObject({ id: A, business_id: B, name: 'Smile Dental', stage: 'lost', lost_reason: 'price' })
    expect(d.business?.website).toBe('https://smile.example.com')
    expect(d.contacts).toHaveLength(1)
    expect(d.suppressedPhones).toEqual(['+919800000001'])
    expect(d.signals[0]!.type).toBe('hiring_frontdesk')
    expect(d.facts[0]!.field).toBe('staff')
    expect(d.score?.total).toBe(78)
    expect(d.pages[0]!.title).toBe('Home')
    expect(d.activities[0]!.type).toBe('note')
    expect(d.money).toEqual({ deal: 150000, retainer: 1500, currency: 'USD' })
  })

  it('has no money for callers and viewers, and INR when the currency is unknown', () => {
    expect(toLeadDetail({ ...json, money: null })!.money).toBeNull()
    expect(toLeadDetail({ ...json, money: { deal: null, retainer: null, currency: 'XYZ' } })!.money).toEqual({ deal: null, retainer: null, currency: 'INR' })
  })

  it('fills a missing name, stage or reason', () => {
    const d = toLeadDetail({ ...json, lead: { id: A, business_id: B, name: null, stage: null } })!
    expect(d.lead).toMatchObject({ name: 'Unnamed business', stage: 'new', lost_reason: null })
    expect(toLeadDetail({ ...json, business: null, score: null })).toMatchObject({ business: null, score: null })
  })

  it('is null for a lead that does not exist or is not visible', () => {
    expect(toLeadDetail(null)).toBeNull()
    expect(toLeadDetail({ lead: {} })).toBeNull()
  })
})

describe('the board', () => {
  it('sends only the filters in use', () => {
    expect(boardFiltersJson({ seg: '', country: '', owner: '', overdue: false })).toEqual({})
    expect(boardFiltersJson({ seg: 'clinics-in', country: 'in', owner: 'me', overdue: true })).toEqual({
      seg: 'clinics-in',
      country: 'in',
      owner: 'me',
      overdue: true,
    })
  })

  it('maps the cards, with money only where the database added it', () => {
    const board = toBoard({
      cards: [
        { id: A, name: 'Smile Dental', city: 'Pune', grade: 'A', stage: 'proposal_sent', next_step: 'Call', due_at: '2026-11-20', owner_id: B, segment_id: 'clinics-in', country: 'in', last_activity_at: '2026-11-14T00:00:00Z', deal_value_inr: 90000, retainer_monthly_value: null, deal_currency: 'INR' },
        { id: B, name: null, stage: 'talking' },
        { name: 'no id' },
      ],
      counts: { contacted: 120, talking: 4, lost: '30' },
    })
    expect(board.cards).toHaveLength(2)
    expect(board.cards[0]).toEqual({
      id: A,
      name: 'Smile Dental',
      city: 'Pune',
      grade: 'A',
      stage: 'proposal_sent',
      nextStep: 'Call',
      dueAt: '2026-11-20',
      ownerId: B,
      segmentId: 'clinics-in',
      country: 'in',
      lastActivityAt: '2026-11-14T00:00:00Z',
      dealValue: 90000,
      retainer: null,
      currency: 'INR',
    })
    expect(board.cards[1]).toMatchObject({ id: B, name: 'Unnamed business', stage: 'talking' })
    expect('dealValue' in board.cards[1]!).toBe(false)
    expect(board.counts).toEqual({ contacted: 120, talking: 4, lost: 30 })
  })
})

describe('the Leads page', () => {
  it('sends only the filters in use, defaults left out', () => {
    expect(leadsFiltersJson(EMPTY_FILTERS)).toEqual({})
    const json = leadsFiltersJson({
      ...EMPTY_FILTERS,
      q: 'smile',
      seg: ['clinics-in'],
      grade: ['A', 'B'],
      mobile: true,
      owner: 'none',
      from: '2026-11-01',
      sort: 'score',
      dir: 'asc',
      page: 3,
    })
    expect(json).toEqual({ q: 'smile', seg: ['clinics-in'], grade: ['A', 'B'], mobile: true, owner: 'none', from: '2026-11-01', sort: 'score', dir: 'asc' })
  })

  it('maps a page, cities sorted for people and views split into mine and shared', () => {
    const page = toLeadsPage(
      {
        rows: [
          { id: A, business_id: B, name: 'Smile Dental', stage: 'new', total: 82, deal_value_inr: 50000 },
          { id: B, business_id: A, name: null, stage: null },
        ],
        total: 1234,
        page: 2,
        page_size: 50,
        cities: ['pune', 'Ahmedabad', 'Dubai', '', 7],
        views: [
          { id: 'v1', name: 'Mine', shared: false, mine: true, qs: 'grade=A' },
          { id: 'v2', name: 'Team', shared: true, mine: false, qs: 'stage=talking' },
          { id: 'v3', name: 'Mine shared', shared: true, mine: true, qs: null },
        ],
      },
      { page: 2, pageSize: 50 },
    )
    expect(page.total).toBe(1234)
    expect(page.rows[0]).toMatchObject({ id: A, deal_value_inr: 50000 })
    expect(page.rows[1]).toMatchObject({ name: 'Unnamed business', stage: 'new' })
    expect('deal_value_inr' in page.rows[1]!).toBe(false)
    expect(page.cities).toEqual(['Ahmedabad', 'Dubai', 'pune'])
    expect(page.views.mine.map((v) => v.name)).toEqual(['Mine', 'Mine shared'])
    expect(page.views.shared.map((v) => v.name)).toEqual(['Team'])
    expect(page.views.mine[1]!.qs).toBe('')
  })

  it('falls back to what was asked for', () => {
    expect(toLeadsPage(null, { page: 4, pageSize: 50 })).toEqual({ rows: [], total: 0, page: 4, pageSize: 50, cities: [], views: { mine: [], shared: [] } })
  })
})

describe('toSearchResults', () => {
  it('maps the results and skips anything without an id', () => {
    expect(toSearchResults([{ id: A, name: 'Smile Dental', city: 'Pune', country: 'in', web_domain: 'smile.example.com', segment_id: 'clinics-in', grade: 'A', stage: 'new', created_at: '2026-11-14T00:00:00Z' }, { name: 'x' }])).toEqual([
      { id: A, name: 'Smile Dental', city: 'Pune', country: 'in', webDomain: 'smile.example.com', segmentId: 'clinics-in', grade: 'A', stage: 'new', createdAt: '2026-11-14T00:00:00Z' },
    ])
    expect(toSearchResults(null)).toEqual([])
  })
})

describe('toInsights', () => {
  const counts = { leads: 100, contacted: 40, replied: 10, meetings: 4, proposals: 2, won: 1 }
  const json = {
    total: counts,
    by_segment: [{ id: 'clinics-in', ...counts }],
    by_group: [{ id: 'none', ...counts }],
    quality: { leads: 100, with_phone: 80, own_phone: 50, contacted: 40, wrong: 4, median_signal_age_days: 2.5, votes: 10, up_votes: 7 },
    costs: {
      days: [
        { day: '2026-11-14', inr: 300.25 },
        { day: '2026-11-15', inr: 199.75 },
      ],
      spend: 500,
      cap: 750,
      researched: 250,
      good_leads: 20,
      won: 0,
    },
  }

  it('turns the counts into rates', () => {
    const i = toInsights(json)
    expect(i.total).toEqual(counts)
    expect(i.bySegment[0]).toEqual({ id: 'clinics-in', ...counts })
    expect(i.quality).toEqual({ leads: 100, phoneRate: 0.8, ownPhoneRate: 0.5, wrongRate: 0.1, medianSignalAgeDays: 2.5, thumbsUpRate: 0.7, votes: 10 })
  })

  it('works out the unit costs, with none for nothing won', () => {
    expect(toInsights(json).costs).toEqual({
      days: json.costs.days,
      cap: 750,
      spend: 500,
      perResearched: 2,
      perGoodLead: 25,
      perWon: null,
      researched: 250,
      goodLeads: 20,
      won: 0,
    })
  })

  it('has no rates without data and no costs for callers and viewers', () => {
    const i = toInsights({ ...json, quality: { leads: 0, votes: 0 }, costs: null })
    expect(i.costs).toBeNull()
    expect(i.quality).toEqual({ leads: 0, phoneRate: null, ownPhoneRate: null, wrongRate: null, medianSignalAgeDays: null, thumbsUpRate: null, votes: 0 })
  })
})

describe('toEngineLive', () => {
  it('counts per segment as maps', () => {
    const e = toEngineLive({
      spend_today: 123.45,
      researched_yesterday: { 'clinics-in': 300 },
      leads_yesterday: { 'clinics-in': 12, 'clinics-ae': 3 },
      sources: [{ source: 'gdelt', enabled: true, health: 'ok' }],
      runs: [{ id: 'r1', kind: 'night', status: 'ok' }],
      queries: [],
    })
    expect(e.spendToday).toBe(123.45)
    expect(e.researchedBy.get('clinics-in')).toBe(300)
    expect(e.leadsBy.get('clinics-ae')).toBe(3)
    expect(e.sources).toHaveLength(1)
    expect(e.runs[0]!.kind).toBe('night')
    expect(toEngineLive(null)).toMatchObject({ spendToday: 0, sources: [], runs: [], queries: [] })
  })
})
