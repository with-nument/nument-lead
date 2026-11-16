// Short, plain lines for the Settings rows. Pure, so they are unit tested.
import { NOTIFY_KINDS, NOTIFY_KIND_LABEL, type Recipient } from '@/lib/notify'

/** What a person gets by email, in a few words. */
export function recipientSummary(r: Pick<Recipient, 'morning' | 'alerts' | 'weekly' | 'active'>) {
  if (!r.active) return 'Paused: gets no email'
  const on = NOTIFY_KINDS.filter((k) => r[k]).map((k) => NOTIFY_KIND_LABEL[k])
  return on.length ? on.join(', ') : 'Gets no email'
}

export type SuppressionEntry = { id: string; phone_e164: string | null; email: string | null; web_domain: string | null; reason: string }

/** The kind and value of a Do not contact entry, as the add form takes them (for Undo). */
export function suppressionInput(e: SuppressionEntry): { kind: 'phone' | 'email' | 'domain'; value: string } | null {
  if (e.phone_e164) return { kind: 'phone', value: e.phone_e164 }
  if (e.email) return { kind: 'email', value: e.email }
  if (e.web_domain) return { kind: 'domain', value: e.web_domain }
  return null
}

/** "12 emails, 3 phones and 4 websites", leaving out kinds with none. */
export function suppressionCounts(entries: readonly SuppressionEntry[]): string {
  const n = { email: 0, phone: 0, domain: 0 }
  for (const e of entries) {
    const k = suppressionInput(e)?.kind
    if (k) n[k]++
  }
  const parts = [
    n.email ? `${n.email} ${n.email === 1 ? 'email' : 'emails'}` : '',
    n.phone ? `${n.phone} ${n.phone === 1 ? 'phone' : 'phones'}` : '',
    n.domain ? `${n.domain} ${n.domain === 1 ? 'website' : 'websites'}` : '',
  ].filter(Boolean)
  if (!parts.length) return 'Nobody yet'
  return parts.length === 1 ? parts[0]! : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}
