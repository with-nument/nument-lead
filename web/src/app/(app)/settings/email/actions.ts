'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { fail, fieldErrorsOf, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { FIELD_LABEL, NewRecipient, RecipientToggle, type RecipientField } from '@/lib/notify'

// Who gets the engine's emails. Admin only; Row Level Security enforces the same in the database.

export async function addRecipient(_: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = NewRecipient.safeParse({ email: String(formData.get('email') ?? ''), name: String(formData.get('name') ?? '') })
  if (!parsed.success) return fail('Check the highlighted fields.', fieldErrorsOf(parsed.error))
  const sb = await createClient()
  const { error } = await sb.from('notify_recipients').insert({ email: parsed.data.email, name: parsed.data.name, created_by: user.id })
  if (error) {
    if (error.code === '23505') return fail('That email is already on the list.', { email: ['Already on the list.'] })
    console.error('addRecipient failed', error.code)
    return fail(SAVE_FAILED)
  }
  revalidatePath('/settings/email')
  return ok(`Added ${parsed.data.email}`)
}

export async function updateRecipient(input: { id: string; field: string; value: boolean }): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = RecipientToggle.safeParse(input)
  if (!parsed.success) return fail('Recipient not found.')
  const { id, field, value } = parsed.data
  const sb = await createClient()
  const patch: Partial<Record<RecipientField, boolean>> = { [field]: value }
  const { data, error } = await sb.from('notify_recipients').update(patch).eq('id', id).select('id')
  if (error) return fail(SAVE_FAILED)
  if (!data?.length) return fail('Recipient not found.')
  revalidatePath('/settings/email')
  return ok(`${FIELD_LABEL[field]} ${value ? 'on' : 'off'}`)
}

export async function removeRecipient(id: string): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = z.uuid().safeParse(id)
  if (!parsed.success) return fail('Recipient not found.')
  const sb = await createClient()
  const { error } = await sb.from('notify_recipients').delete().eq('id', parsed.data)
  if (error) return fail(SAVE_FAILED)
  revalidatePath('/settings/email')
  return ok('Removed from email')
}
