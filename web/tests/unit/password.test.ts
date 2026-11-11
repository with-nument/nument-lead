import { describe, expect, it } from 'vitest'
import { PasswordSchema, generateTempPassword } from '@/lib/password'

describe('PasswordSchema', () => {
  it('rejects short or simple passwords', () => {
    expect(PasswordSchema.safeParse('Short1!').success).toBe(false)
    expect(PasswordSchema.safeParse('alllowercase123!').success).toBe(false)
    expect(PasswordSchema.safeParse('NoNumbersHere!!').success).toBe(false)
    expect(PasswordSchema.safeParse('NoSymbols12345').success).toBe(false)
  })

  it('accepts a strong password', () => {
    expect(PasswordSchema.safeParse('Calm-Indigo-2026!').success).toBe(true)
  })
})

describe('generateTempPassword', () => {
  it('always satisfies the password rules', () => {
    for (let i = 0; i < 200; i++) {
      const p = generateTempPassword()
      expect(p).toHaveLength(16)
      expect(PasswordSchema.safeParse(p).success).toBe(true)
    }
  })

  it('does not repeat', () => {
    const set = new Set(Array.from({ length: 100 }, () => generateTempPassword()))
    expect(set.size).toBe(100)
  })
})
