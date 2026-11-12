import { z } from 'zod'
import { getSessionUser } from '@/lib/auth'
import { env } from '@/lib/env'
import { isReservedAddress, testEmail } from '@/lib/notify'
import { sendEmail } from '@/lib/resend'
import { createClient } from '@/lib/supabase/server'

// Settings > Email recipients > Send test: one sample email to one recipient on the list. Admin only.
// Only addresses already on the list can be mailed, so this never sends to an arbitrary address.

const Body = z.object({ id: z.uuid() })

/** Like Server Actions: a browser Origin header must match the host the request was sent to. */
function sameSite(request: Request) {
  const origin = request.headers.get('origin')
  if (!origin) return true
  const host = request.headers.get('x-forwarded-host') ?? request.headers.get('host')
  try {
    return new URL(origin).host === host
  } catch {
    return false
  }
}

const reply = (status: number, ok: boolean, message: string) => Response.json({ ok, message }, { status })

export async function POST(request: Request) {
  const user = await getSessionUser()
  if (!user) return reply(401, false, 'Sign in again.')
  if (user.role !== 'admin') return reply(403, false, 'Only admins can send test emails.')
  // Same-site requests only: a page elsewhere must never trigger a send with this session.
  if (!sameSite(request)) return reply(403, false, 'Send the test from the app.')
  const parsed = Body.safeParse(await request.json().catch(() => null))
  if (!parsed.success) return reply(400, false, 'Recipient not found.')

  const sb = await createClient()
  const { data: r } = await sb.from('notify_recipients').select('email, name, morning, alerts, weekly, active').eq('id', parsed.data.id).maybeSingle()
  if (!r) return reply(404, false, 'Recipient not found.')
  if (isReservedAddress(r.email)) return reply(422, false, `${r.email} is a test address, so nothing was sent.`)

  const appUrl = env().NEXT_PUBLIC_APP_URL ?? new URL(request.url).origin
  const sent = await sendEmail(r.email, testEmail(r, appUrl))
  if (sent.ok) return reply(200, true, `Test email sent to ${r.email}`)
  if (sent.reason === 'not_configured') return reply(503, false, 'Email is not set up on the server yet (RESEND_API_KEY).')
  return reply(502, false, 'Resend did not accept the email. Try again in a minute.')
}
