import { describe, expect, it } from 'vitest'
import { countWords, lintMessage } from '@/lib/lint'

const GOOD =
  'Hi Dr Mehta, saw your Baner clinic is hiring a receptionist to handle calls and bookings. We are Nument, a small team that sets up WhatsApp booking replies so patients get answers even when the desk is busy. Would a short look at how it works be useful?'

describe('lintMessage (same rules as the engine, plan 12.5)', () => {
  it('passes a good first message', () => {
    expect(countWords(GOOD)).toBeGreaterThanOrEqual(30)
    expect(lintMessage(GOOD)).toEqual([])
  })

  it('flags word counts outside 30 to 60', () => {
    expect(lintMessage('Hi Asha, Nument here. Can we talk?')[0]).toMatch(/words \(want 30 to 60\)/)
  })

  it('needs exactly one question mark', () => {
    expect(lintMessage(GOOD.replace('useful?', 'useful.'))).toContain('0 question marks (want exactly 1)')
    expect(lintMessage(`${GOOD} Free now?`)).toContain('2 question marks (want exactly 1)')
  })

  it('rejects links, dashes, emojis and prices', () => {
    expect(lintMessage(GOOD.replace('works', 'works at nument.in'))).toContain('Contains a link')
    expect(lintMessage(GOOD.replace('busy.', 'busy \u2014 always.'))).toContain('Contains a dash')
    expect(lintMessage(GOOD.replace('busy.', 'busy - always.'))).toContain('Contains a dash')
    expect(lintMessage(GOOD.replace('busy.', 'busy \u{1F600}.'))).toContain('Contains an emoji')
    expect(lintMessage(GOOD.replace('busy.', 'busy, from ₹15,000.'))).toContain('Mentions a price')
  })

  it('keeps normal hyphenated words', () => {
    expect(lintMessage(GOOD.replace('calls', 'follow-up calls'))).toEqual([])
  })

  it('rejects banned phrases', () => {
    const problems = lintMessage(GOOD.replace('We are Nument', 'Kindly note we are Nument'))
    expect(problems).toContain('Banned phrase "kindly"')
  })

  it('checks the greeting and the brand on first messages only', () => {
    const noHi = GOOD.replace('Hi Dr Mehta,', 'Dear Dr Mehta,')
    expect(lintMessage(noHi)).toContain("Must start with 'Hi'")
    expect(lintMessage(GOOD.replace('Nument', 'our studio'))).toContain('Does not name Nument')
    expect(lintMessage('Hello again, just checking whether you saw my note about WhatsApp booking replies for the clinic?', 'followup_d3')).toEqual([])
  })
})
