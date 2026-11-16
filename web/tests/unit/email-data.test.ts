import { describe, expect, it } from 'vitest'
import {
  inrShort,
  isEditable,
  rangeText,
  shortWhen,
  stepLabel,
  toCallsPage,
  toInboxPage,
  toLeadConversation,
} from '@/lib/queries/email-data'

// The JSON shapes come from supabase/migrations/0033_inbox_calls.sql (engine/tests/test_inbox_calls.py checks them).

describe('inbox_page', () => {
  it('reads a page with counts, items and the next cursor', () => {
    const page = toInboxPage({
      tab: 'replies',
      counts: { replies: 4, review: '2', done: 10 },
      items: [
        {
          key: 'm1',
          tab: 'replies',
          at: '2026-11-16T02:42:00Z',
          thread_id: 't1',
          lead_id: 'l1',
          company: 'Leafline',
          contact_name: 'Maya Rao',
          contact_role: 'Co-founder',
          inbound: { id: 'm1', body: 'Open to a call', classification: 'interested', confidence: 0.93 },
          draft: { id: 'd1', step: null, body: 'Hi Maya', status: 'review' },
          last_out: { id: 'o1', step: 0, subject: 'WhatsApp orders', at: '2026-11-10T05:00:00Z' },
        },
      ],
      next_cursor: { at: '2026-11-16T02:42:00Z', id: 'm1' },
    })
    expect(page.counts).toEqual({ replies: 4, review: 2, done: 10 })
    const [item] = page.items
    expect(item?.inbound?.classification).toBe('interested')
    expect(item?.draft).toMatchObject({ id: 'd1', step: null, status: 'review' })
    expect(item?.lastOut?.subject).toBe('WhatsApp orders')
    expect(page.nextCursor).toEqual({ at: '2026-11-16T02:42:00Z', id: 'm1' })
  })

  it('survives null and junk', () => {
    expect(toInboxPage(null)).toEqual({ tab: 'replies', counts: { replies: 0, review: 0, done: 0 }, items: [], nextCursor: null })
    const page = toInboxPage({ tab: 'nope', items: [{ key: 'x', draft: { status: 'weird' } }] })
    expect(page.items[0]?.draft?.status).toBe('draft')
    expect(page.items[0]?.inbound).toBeNull()
  })
})

describe('calls_page', () => {
  it('reads the brief, the offer range and plan views', () => {
    const calls = toCallsPage({
      today: [
        {
          lead_id: 'l1',
          meeting_at: '2026-11-16T13:00:00Z',
          company: 'Quill Legal',
          booking: { kind: 'booked', start: '2026-11-16T13:00:00Z', end: '2026-11-16T13:20:00Z', location: 'https://meet.google.com/x' },
          brief: { at: '2026-11-16T01:40:00Z', content: { summary: 'Two lawyers', why_now: 'Raised', what_they_need: ['A'], questions: ['1', '2', '3'] } },
          offer: { key: 'mvp_sprint', name: 'MVP sprint', typical_range: { usd: [3000, 12000], inr: [150000, 600000] } },
          plan: { views: 2 },
          proposal: { id: 'p1', status: 'draft', call_notes: 'NDAs', drafted: false },
        },
      ],
      upcoming: [],
    })
    const [c] = calls.today
    expect(c?.brief?.content?.questions).toHaveLength(3)
    expect(c?.offer && rangeText(c.offer.range)).toBe('₹1.5L to ₹6L')
    expect(c?.plan?.views).toBe(2)
    expect(c?.proposal).toMatchObject({ callNotes: 'NDAs', drafted: false })
    expect(calls.earlier).toEqual([])
  })
})

describe('lead_conversation', () => {
  it('is null for a lead that is not visible', () => {
    expect(toLeadConversation(null)).toBeNull()
  })

  it('adds up plan views and keeps profile evidence', () => {
    const conv = toLeadConversation({
      lead_id: 'l1',
      messages: [{ id: 'a', direction: 'in', status: 'received', body: 'Hi' }],
      plan_pages: [{ token: 't', views: 2 }, { token: 'u', kind: 'proposal', views: 1 }],
      startup_profile: { team_size: 3, tech_team: 'none', evidence: { tech_team: { ids: ['f1'], why: 'no engineers' } } },
      offers: [{ rank: 2, key: 'ai_feature', typical_range: { inr_month: [20000, 80000] } }],
    })
    expect(conv?.planViews).toBe(3)
    expect(conv?.planPages[1]?.kind).toBe('proposal')
    expect(conv?.messages[0]?.direction).toBe('in')
    expect(conv?.startupProfile?.evidence.tech_team).toEqual({ ids: ['f1'], why: 'no engineers' })
    expect(conv?.offers[0] && rangeText(conv.offers[0].range)).toBe('₹20K to ₹80K a month')
  })
})

describe('helpers', () => {
  it('formats short times in India time', () => {
    const now = new Date('2026-11-16T06:00:00Z') // 11:30 am in India
    expect(shortWhen('2026-11-16T02:42:00Z', now)).toBe('8:12 am')
    expect(shortWhen('2026-11-15T10:00:00Z', now)).toBe('Yesterday')
    expect(shortWhen('2026-11-10T10:00:00Z', now)).toBe('10 Nov')
    expect(shortWhen(null, now)).toBe('')
  })

  it('names steps, amounts and editable states', () => {
    expect(stepLabel(0)).toBe('Day 0')
    expect(stepLabel(null)).toBe('Reply')
    expect(inrShort(250000)).toBe('₹2.5L')
    expect(inrShort(12000000)).toBe('₹1.2Cr')
    expect(isEditable('approved')).toBe(true)
    expect(isEditable('sent')).toBe(false)
  })
})
