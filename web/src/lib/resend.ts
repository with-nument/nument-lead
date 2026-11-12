import 'server-only'
import { env } from '@/lib/env'

export const RESEND_URL = 'https://api.resend.com/emails'

export type SendResult = { ok: true } | { ok: false; reason: 'not_configured' | 'rejected' | 'network' }

/**
 * One email to one address through Resend's HTTP API. RESEND_API_KEY is a server-only variable (never
 * NEXT_PUBLIC_). The sender and reply-to match the engine's ALERT_EMAIL_FROM and ALERT_REPLY_TO.
 */
export async function sendEmail(to: string, email: { subject: string; html: string; text: string }): Promise<SendResult> {
  const { RESEND_API_KEY, ALERT_EMAIL_FROM, ALERT_REPLY_TO } = env()
  if (!RESEND_API_KEY) return { ok: false, reason: 'not_configured' }
  try {
    const res = await fetch(RESEND_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: ALERT_EMAIL_FROM, to: [to], reply_to: ALERT_REPLY_TO, ...email }),
      signal: AbortSignal.timeout(15_000),
      cache: 'no-store',
    })
    if (!res.ok) {
      console.error('resend rejected the email', res.status)
      return { ok: false, reason: 'rejected' }
    }
    return { ok: true }
  } catch (error) {
    console.error('resend unreachable', error instanceof Error ? error.name : 'unknown')
    return { ok: false, reason: 'network' }
  }
}

export const emailConfigured = () => Boolean(env().RESEND_API_KEY)
