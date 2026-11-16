import { describe, expect, it } from 'vitest'
import { callsFrom, excerpt, overnightHealth, overnightStats, proposalsFrom, repliesFrom, toOvernight } from '@/app/(v2)/v2/_today/email'
import { rangeText, toCallsPage, toInboxPage } from '@/lib/queries/email-data'

// 16 Nov 2026 (a Monday), 9:00 in India.
const now = new Date('2026-11-16T03:30:00Z')

describe('Today from the email functions', () => {
  it('cuts an email to one line without the greeting or the sign-off', () => {
    expect(excerpt('Hi Maya,\n\nYes, open to a call next week.\n\nBest,\nMaya')).toBe('Yes, open to a call next week.')
    expect(excerpt('Thanks!\nWorks for us.')).toBe('Works for us.')
    expect(excerpt('word '.repeat(60), 30)).toMatch(/^word( word)*…$/)
    expect(excerpt('word '.repeat(60), 30).length).toBeLessThanOrEqual(30)
    expect(excerpt(null)).toBe('')
  })

  it('turns waiting replies into rows; the drafted answer is what Approve sends', () => {
    const page = toInboxPage({
      tab: 'replies',
      counts: { replies: 7, review: 1, done: 0 },
      items: [
        {
          key: 'k1',
          lead_id: 'l1',
          company: 'Leafline',
          contact_name: 'Maya Rao',
          inbound: { id: 'in1', body: 'Hi,\nRoughly what would a first version cost?' },
          draft: { id: 'd1', step: null, status: 'review', body: 'Hi Maya,\n\nA first version is ₹2L to ₹3L.\n\nTeam Nument' },
        },
        { key: 'k2', lead_id: 'l2', company: 'Mosaic Tutors', contact_name: null, inbound: { id: 'in2', body: 'Not now.' }, draft: null },
        { key: 'k3', lead_id: 'l3', company: 'Done Co', inbound: { id: 'in3', body: 'Ok' }, draft: { id: 'd3', step: null, status: 'approved', body: 'Sure' } },
      ],
    })
    const rows = repliesFrom(page.items)
    expect(rows[0]).toEqual({
      id: 'd1',
      leadId: 'l1',
      person: 'Maya Rao',
      company: 'Leafline',
      quote: 'Roughly what would a first version cost?',
      suggestion: 'A first version is ₹2L to ₹3L.',
      approvable: true,
    })
    // No drafted answer (or one already approved): the row opens the lead instead.
    expect(rows[1]).toMatchObject({ id: 'k2', person: 'Mosaic Tutors', suggestion: null, approvable: false })
    expect(rows[2]).toMatchObject({ id: 'k3', approvable: false })
  })

  const calls = toCallsPage({
    today: [
      {
        lead_id: 'c2',
        meeting_at: '2026-11-16T14:30:00Z',
        company: 'Kindred Pets',
        contact_name: 'Sara Thomas',
        brief: null,
        plan: { views: 2 },
        proposal: null,
      },
      {
        lead_id: 'c1',
        meeting_at: '2026-11-16T13:00:00Z',
        company: 'Quill Legal',
        contact_name: 'Arjun Mehta',
        brief: { at: '2026-11-16T01:00:00Z', content: { summary: 's', what_they_need: ['A contract review assistant'] } },
        proposal: null,
      },
    ],
    upcoming: [],
    earlier: [
      {
        lead_id: 'p1',
        meeting_at: '2026-11-13T10:00:00Z',
        company: 'Orbit Kitchen',
        contact_name: 'Rohan Iyer',
        offer: { key: 'mvp', name: 'MVP sprint', promise: 'p', timeline: '6 weeks', typical_range: { inr: [200000, 300000] } },
        proposal: { id: 'pr1', status: 'draft', drafted: true },
      },
      { lead_id: 'p2', meeting_at: '2026-11-12T10:00:00Z', company: 'Notes only', proposal: { id: 'pr2', status: 'draft', drafted: false } },
      { lead_id: 'p3', meeting_at: '2026-11-01T10:00:00Z', company: 'Sent already', proposal: { id: 'pr3', status: 'sent', drafted: true } },
      { lead_id: 'p4', meeting_at: '2026-11-02T10:00:00Z', company: 'Old call', proposal: { id: 'pr4', status: 'draft', drafted: true } },
    ],
  })

  it('lists today’s calls earliest first, with the brief line and a link to the brief', () => {
    const rows = callsFrom(calls)
    expect(rows.map((r) => [r.time, r.person, r.note, r.href])).toEqual([
      ['6:30 pm', 'Arjun Mehta', 'Brief ready · A contract review assistant', '/calls?lead=c1'],
      ['8:00 pm', 'Sara Thomas', 'Brief on its way · plan viewed 2 times', '/calls?lead=c2'],
    ])
  })

  it('lists drafted proposals that are not sent yet, newest call first', () => {
    const rows = proposalsFrom(calls, now)
    expect(rows.map((r) => r.id)).toEqual(['pr1', 'pr4'])
    expect(rows[0]).toMatchObject({ company: 'Orbit Kitchen', person: 'Rohan Iyer', note: 'Drafted from Friday’s call · MVP sprint, 6 weeks · ₹2L to ₹3L' })
    expect(rows[1]!.note).toBe('Drafted from the call on 2 Nov')
  })

  it('shows the overnight numbers and never an open count', () => {
    const o = toOvernight({ since: '2026-11-15T12:30:00Z', startups_found: 42, startups_qualified: 17, emails_sent: 250, replies: 4, plan_pages_viewed: 6, bounced: 1 })!
    const rows = overnightStats(o)
    expect(rows).toEqual([
      { label: 'Startups found', value: '42' },
      { label: 'Passed every check', value: '17' },
      { label: 'Emails sent', value: '250' },
      { label: 'Replies', value: '4' },
      { label: 'Plan pages viewed', value: '6' },
    ])
    expect(rows.some((r) => /open/i.test(r.label))).toBe(false)
    expect(overnightHealth(o)).toEqual({ tone: 'ok', text: 'Sending is healthy · 0.4% bounced' })
    expect(overnightHealth({ ...o, bounced: 6 })?.tone).toBe('warn')
    expect(overnightHealth({ ...o, bounced: 10 })?.tone).toBe('bad')
    expect(overnightHealth({ ...o, emailsSent: 0 })).toBeNull()
  })

  it('treats a missing overnight function as no card data', () => {
    expect(toOvernight(null)).toBeNull()
    expect(toOvernight({})).toMatchObject({ startupsFound: 0, emailsSent: 0 })
  })
})

describe('excerpt and ranges', () => {
  it('drops a signed name on the last line', () => {
    expect(excerpt('Hi,\nYes, open to a call next week.\nMaya')).toBe('Yes, open to a call next week.')
    expect(excerpt('Sounds good')).toBe('Sounds good')
  })

  it('shows one amount when the range is a single price', () => {
    expect(rangeText({ inr: [240000, 240000], usd: null, monthly: false })).toBe('₹2.4L')
  })
})
