// Message lint, the same rules as the engine (plan 12.5), so the app and the engine never disagree.

export type MessageKind = 'message' | 'message_alt' | 'followup_d3' | 'followup_d7'

const EMOJI = /[\u{1F300}-\u{1FAFF}\u2600-\u27BF\u{1F1E6}-\u{1F1FF}]/u
const PRICE = /₹|\brs\.?\s*\d|\binr\b|\baed\b|\$\s*\d|\blakh\b|\bcrore\b|\bper month\b|\/month|\bk\b\s*(?:per|\/)/i
const LINK = /https?:\/\/|www\.|\.com\b|\.in\b|\.ae\b|\.io\b/i
const DASH = /[\u2013\u2014]| - /
export const BANNED = [
  'businesses like yours', 'ai-powered', 'ai powered', 'hope you are', "hope you're", 'hope this finds',
  'reaching out', 'synergy', 'leverage', 'cutting-edge', 'cutting edge', 'game-changer', 'game changer',
  'revolutioni', 'quick 10-minute call', 'just following up', 'just bumping', 'greetings of the day',
  'dear sir', 'dear madam', 'respected', 'kindly', 'revert', 'we are a leading', 'state-of-the-art',
  'world-class', 'one-stop', 'guaranteed results',
] as const

export const WORD_LIMITS: Record<MessageKind, readonly [number, number]> = {
  message: [30, 60],
  message_alt: [30, 60],
  followup_d3: [15, 45],
  followup_d7: [10, 30],
}

export const countWords = (text: string) => text.split(/\s+/).filter(Boolean).length

/** Problems in plain words. An empty list means the message is fine. */
export function lintMessage(text: string, kind: MessageKind = 'message'): string[] {
  const problems: string[] = []
  const words = countWords(text)
  const [lo, hi] = WORD_LIMITS[kind]
  if (words < lo || words > hi) problems.push(`${words} words (want ${lo} to ${hi})`)
  if (kind === 'message' || kind === 'message_alt') {
    if (!text.startsWith('Hi ') && !text.startsWith('Hi,')) problems.push("Must start with 'Hi'")
    if (!text.includes('Nument')) problems.push('Does not name Nument')
  }
  const questions = (text.match(/\?/g) ?? []).length
  if (questions !== 1) problems.push(`${questions} question marks (want exactly 1)`)
  if (LINK.test(text)) problems.push('Contains a link')
  if (DASH.test(text)) problems.push('Contains a dash')
  if (EMOJI.test(text)) problems.push('Contains an emoji')
  if (PRICE.test(text)) problems.push('Mentions a price')
  const lower = text.toLowerCase()
  for (const b of BANNED) if (lower.includes(b)) problems.push(`Banned phrase "${b}"`)
  return problems
}
