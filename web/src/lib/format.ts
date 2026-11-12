const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('en-IN')

/** "₹1,50,000" */
export const formatInr = (v: number | null | undefined) => (v === null || v === undefined ? '' : inr.format(v))
/** "1,234" */
export const formatNumber = (v: number | null | undefined) => (v === null || v === undefined ? '' : num.format(v))
/** "42%" from a 0 to 1 ratio. */
export const formatPercent = (ratio: number | null | undefined, digits = 0) =>
  ratio === null || ratio === undefined || !Number.isFinite(ratio) ? '' : `${(ratio * 100).toFixed(digits)}%`

/** "Abhigyan Raj" becomes "AR". */
export function initials(name: string | null | undefined) {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? (parts.at(-1)?.[0] ?? '') : '')).toUpperCase() || '?'
}

/** Host name without "www." for display. */
export function hostOf(url: string | null | undefined) {
  if (!url) return ''
  try {
    return new URL(url.startsWith('http') ? url : `https://${url}`).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** A safe absolute http(s) URL for links, or null. */
export function safeUrl(url: string | null | undefined) {
  if (!url) return null
  try {
    const u = new URL(url.startsWith('http') ? url : `https://${url}`)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.toString() : null
  } catch {
    return null
  }
}
