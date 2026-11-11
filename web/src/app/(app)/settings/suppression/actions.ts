'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { fail, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { toE164 } from '@/lib/phone'
import { SUPPRESSION_REASONS } from '@/lib/suppression'

const Entry = z.object({
  kind: z.enum(['phone', 'email', 'domain']),
  value: z.string().trim().min(3, 'Enter a phone, email or website.').max(254),
  reason: z.enum(SUPPRESSION_REASONS),
})

/** Admin only: never contact this phone, email or website again. */
export async function addSuppression(_: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = Entry.safeParse(Object.fromEntries(formData))
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the entry.')
  const { kind, value, reason } = parsed.data
  let row: { phone_e164?: string; email?: string; web_domain?: string }
  if (kind === 'phone') {
    const phone = toE164(value)
    if (!phone) return fail('That does not look like a phone number. Include the country code, for example +91 98110 12345.')
    row = { phone_e164: phone }
  } else if (kind === 'email') {
    const email = z.email().safeParse(value.toLowerCase())
    if (!email.success) return fail('That does not look like an email.')
    row = { email: email.data }
  } else {
    const domain = value.toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0] ?? ''
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(domain)) return fail('That does not look like a website, for example clinic.com.')
    row = { web_domain: domain }
  }
  const sb = await createClient()
  const { error } = await sb.from('suppression').insert({ ...row, reason, added_by: user.id })
  if (error) {
    if (error.code === '23505') return fail('That is already on the list.')
    return fail(SAVE_FAILED)
  }
  revalidatePath('/settings/suppression')
  return ok('Added to Do not contact')
}

export async function removeSuppression(id: string): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = z.uuid().safeParse(id)
  if (!parsed.success) return fail('Entry not found.')
  const sb = await createClient()
  const { error } = await sb.from('suppression').delete().eq('id', parsed.data)
  if (error) return fail(SAVE_FAILED)
  revalidatePath('/settings/suppression')
  return ok('Removed from Do not contact')
}
