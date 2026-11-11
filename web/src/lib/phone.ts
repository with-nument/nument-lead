/** Digits only, for links and search: "+91 98110 12345" becomes "919811012345". */
export const phoneDigits = (phone: string) => phone.replace(/\D/g, '')

/**
 * Readable phone number from E.164.
 * India mobiles: "+91 98110 12345". UAE: "+971 50 123 4567". Others: country code, then the rest.
 */
export function formatPhone(e164: string | null | undefined) {
  if (!e164) return ''
  const d = phoneDigits(e164)
  if (d.startsWith('91') && d.length === 12) return `+91 ${d.slice(2, 7)} ${d.slice(7)}`
  if (d.startsWith('971') && d.length === 12) return `+971 ${d.slice(3, 5)} ${d.slice(5, 8)} ${d.slice(8)}`
  if (d.startsWith('971') && d.length === 11) return `+971 ${d.slice(3, 4)} ${d.slice(4, 7)} ${d.slice(7)}`
  if (d.startsWith('1') && d.length === 11) return `+1 ${d.slice(1, 4)} ${d.slice(4, 7)} ${d.slice(7)}`
  return `+${d}`
}

/**
 * Normalise a phone typed by a person into E.164, or null when it cannot be one.
 * A bare 10-digit Indian number gets +91.
 */
export function toE164(input: string, defaultCountry: '91' | '971' = '91') {
  const trimmed = input.trim()
  let d = phoneDigits(trimmed)
  if (!d) return null
  if (!trimmed.startsWith('+')) {
    if (d.startsWith('00')) d = d.slice(2)
    else if (d.length === 10 && defaultCountry === '91') d = `91${d}`
    else if (d.startsWith('0') && defaultCountry === '971') d = `971${d.slice(1)}`
  }
  return /^[1-9]\d{6,14}$/.test(d) ? `+${d}` : null
}
