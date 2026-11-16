import { describe, expect, it } from 'vitest'
import { firstStep, followupsFrom, greeting, headline, pipelineStats, startupSummary, thingsToDo, type TodayData } from '@/app/(v2)/v2/_today/build'
import { navCount } from '@/components/shell2/nav-items'
import { toHomeSummary } from '@/lib/queries/page-data'

const summary = toHomeSummary({
  counts: { ready: 2, contacted_this_week: 5, talking: 1, discovery: 0, proposals: 1, overdue: 3 },
  won_this_month_inr: null,
  send: [
    { lead_id: 'a', company: 'Fieldnote', grade: 'A', email: 'x@f.in', phone_e164: null },
    { lead_id: 'b', company: 'Sprout', grade: 'B', email: null, phone_e164: '+911' },
  ],
  followups: [
    { lead_id: 'c', company: 'Tessera', which: 'd3', due_on: '2026-11-16', contact_name: 'Dev' },
    { lead_id: 'd', company: 'Orbit', which: 'd7', due_on: '2026-11-10', contact_name: null },
  ],
})

const empty: TodayData = { replies: [], calls: [], proposals: [], followups: [], startups: [] }
// 16 Nov 2026, 9:00 in India.
const morning = new Date('2026-11-16T03:30:00Z')

describe('v2 Today', () => {
  it('turns follow-ups into rows with a due line', () => {
    const rows = followupsFrom(summary, '2026-11-16')
    expect(rows.map((r) => r.note)).toEqual(['Day 3 follow-up · due today', 'Day 7 follow-up · overdue'])
    expect(rows[1]!.overdue).toBe(true)
  })

  it('counts the startup batch as one thing and puts the solid button on the first step with work', () => {
    const d: TodayData = { ...empty, followups: followupsFrom(summary, '2026-11-16'), startups: [{ leadId: 'a', company: 'F', grade: 'A', city: null, person: null, signal: null }] }
    expect(thingsToDo(d)).toBe(3)
    expect(firstStep(d)).toBe('followups')
    expect(firstStep(empty)).toBeNull()
  })

  it('writes the header in plain words', () => {
    expect(greeting(morning)).toBe('Good morning')
    const h = headline({ ...empty, replies: [{ id: '1', leadId: 'a', person: 'Maya', company: 'Leafline', quote: 'Yes', suggestion: null }, { id: '2', leadId: 'b', person: 'Ishaan', company: 'Mosaic', quote: 'Later', suggestion: null }], calls: [{ id: 'c', leadId: 'c', time: '6:30 pm', person: 'Arjun', company: 'Quill', note: null }] }, morning)
    expect(h.title).toBe('Good morning. 3 things need you today.')
    expect(h.compact).toBe('3 things need you')
    expect(h.subtitle).toBe('Start with 2 replies. Your first call is at 6:30 pm.')
    expect(headline(empty, morning).title).toBe('Good morning. Nothing needs you right now.')
  })

  it('describes the batch from its rows and never shows opens', () => {
    expect(startupSummary(summary)).toBe('All grade A or B · 1 with an email · 1 with a published phone')
    const labels = pipelineStats(summary).map((r) => r.label.toLowerCase())
    expect(labels.some((l) => l.includes('open'))).toBe(false)
  })

  it('shows nav counts only where there is data, and Today like the Today page', () => {
    const counts = { ready: 4, followupsDue: 2, overdue: 0, deals: 3, inboxNew: 0 }
    expect(navCount('/', counts)).toBe(3)
    expect(navCount('/deals', counts)).toBe(3)
    expect(navCount('/inbox', counts)).toBeNull()
    expect(navCount('/calls', counts)).toBeNull()
    expect(navCount('/', null)).toBeNull()
  })
})
