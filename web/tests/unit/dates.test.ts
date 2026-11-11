import { describe, expect, it } from 'vitest'
import { addDays, dueState, formatDate, formatDateTime, formatWeekday, istDate, istMidnightUtc, relativeAge, startOfMonthIst, startOfWeekIst } from '@/lib/dates'

describe('India time formatting', () => {
  it('shows UTC instants in IST', () => {
    expect(formatDateTime('2026-11-12T11:00:00Z')).toBe('12 Nov, 4:30 pm')
    expect(formatWeekday('2026-11-12T11:00:00Z')).toBe('Thu 12 Nov')
  })

  it('uses the India date around midnight', () => {
    // 19:00 UTC on the 11th is 00:30 on the 12th in India.
    expect(istDate(new Date('2026-11-11T19:00:00Z'))).toBe('2026-11-12')
    expect(istDate(new Date('2026-11-11T18:00:00Z'))).toBe('2026-11-11')
  })

  it('finds midnight, the week start and the month start in India', () => {
    expect(istMidnightUtc('2026-11-12')).toBe('2026-11-11T18:30:00.000Z')
    // Thursday 12 Nov 2026: the week starts on Monday 9 Nov.
    expect(startOfWeekIst(new Date('2026-11-12T06:00:00Z'))).toBe('2026-11-08T18:30:00.000Z')
    expect(startOfMonthIst(new Date('2026-11-12T06:00:00Z'))).toBe('2026-10-31T18:30:00.000Z')
  })

  it('adds days across month ends', () => {
    expect(addDays('2026-11-29', 3)).toBe('2026-12-02')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('shows the year only when it is not this year', () => {
    const now = new Date('2026-11-12T06:00:00Z')
    expect(formatDate('2026-11-03', now)).toBe('3 Nov')
    expect(formatDate('2025-11-03', now)).toBe('3 Nov 2025')
  })

  it('says how old a signal is', () => {
    const now = new Date('2026-11-12T06:00:00Z')
    expect(relativeAge('2026-11-08T06:00:00Z', now)).toBe('4 days ago')
    expect(relativeAge('2026-11-12T05:59:40Z', now)).toBe('just now')
    expect(relativeAge('2026-11-12T03:00:00Z', now)).toBe('3 hours ago')
  })

  it('labels due dates', () => {
    expect(dueState('2026-11-11', '2026-11-12')).toBe('overdue')
    expect(dueState('2026-11-12', '2026-11-12')).toBe('today')
    expect(dueState('2026-11-15', '2026-11-12')).toBe('later')
    expect(dueState(null, '2026-11-12')).toBe('none')
  })
})
