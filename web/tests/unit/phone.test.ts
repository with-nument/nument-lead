import { describe, expect, it } from 'vitest'
import { formatPhone, toE164 } from '@/lib/phone'

describe('phones', () => {
  it('formats Indian and UAE numbers', () => {
    expect(formatPhone('+919811012345')).toBe('+91 98110 12345')
    expect(formatPhone('+971501234567')).toBe('+971 50 123 4567')
    expect(formatPhone('+442071234567')).toBe('+442071234567')
    expect(formatPhone(null)).toBe('')
  })

  it('normalises typed numbers to E.164', () => {
    expect(toE164('98110 12345')).toBe('+919811012345')
    expect(toE164('+91 98110-12345')).toBe('+919811012345')
    expect(toE164('0091 98110 12345')).toBe('+919811012345')
    expect(toE164('050 123 4567', '971')).toBe('+971501234567')
    expect(toE164('12')).toBeNull()
  })
})
