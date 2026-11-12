import { z } from 'zod'

/** One password rule for every form (Supabase enforces the same minimum on the server). */
export const PasswordSchema = z
  .string()
  .min(12, 'Use at least 12 characters.')
  .max(72, 'Use at most 72 characters.')
  .regex(/[a-z]/, 'Add a lowercase letter.')
  .regex(/[A-Z]/, 'Add an uppercase letter.')
  .regex(/[0-9]/, 'Add a number.')
  .regex(/[^A-Za-z0-9]/, 'Add a symbol.')

const LOWER = 'abcdefghijkmnopqrstuvwxyz'
const UPPER = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
const DIGITS = '23456789'
const SYMBOLS = '!@#$%^&*-_=+?'

/** A 16-character temporary password with every character class, from a secure random source. */
export function generateTempPassword(length = 16): string {
  const all = LOWER + UPPER + DIGITS + SYMBOLS
  const pick = (set: string) => {
    const buf = new Uint32Array(1)
    // Rejection sampling keeps the choice unbiased.
    const limit = Math.floor(0x1_0000_0000 / set.length) * set.length
    do crypto.getRandomValues(buf)
    while (buf[0]! >= limit)
    return set[buf[0]! % set.length]!
  }
  const chars = [pick(LOWER), pick(UPPER), pick(DIGITS), pick(SYMBOLS)]
  while (chars.length < length) chars.push(pick(all))
  // Fisher-Yates shuffle so the class order is not predictable.
  for (let i = chars.length - 1; i > 0; i--) {
    const buf = new Uint32Array(1)
    crypto.getRandomValues(buf)
    const j = buf[0]! % (i + 1)
    ;[chars[i], chars[j]] = [chars[j]!, chars[i]!]
  }
  return chars.join('')
}
