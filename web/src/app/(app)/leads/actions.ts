'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { logActivity } from '@/lib/activity'
import { fail, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { istDate } from '@/lib/dates'
import { nextStepAndDue } from '@/lib/next-step'
import { revalidateLead } from '@/lib/revalidate'
import { STAGE_VALUES } from '@/lib/stages'

const Ids = z.array(z.uuid()).min(1, 'Select at least one lead.').max(200, 'Select at most 200 leads at a time.')

/** Bulk stage change: the same rule as one change (next step recomputed), one activity per lead via the trigger. */
export async function bulkUpdateStage(input: { ids: string[]; stage: string }): Promise<ActionResult> {
  await requireRole(['admin', 'caller'])
  const parsed = z.object({ ids: Ids, stage: z.enum(STAGE_VALUES) }).safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the selection.')
  const { ids, stage } = parsed.data
  const sb = await createClient()
  const { data: rows, error } = await sb
    .from('v_leads_caller')
    .select('id, stage, wa_at, call_at, d3_at, d7_at, meeting_at')
    .in('id', ids)
  if (error) return fail(SAVE_FAILED)
  const today = istDate()
  let failed = 0
  for (let i = 0; i < (rows ?? []).length; i += 10) {
    const chunk = (rows ?? []).slice(i, i + 10)
    const results = await Promise.all(
      chunk.map((r) => {
        const step = nextStepAndDue({ ...r, stage }, today)
        return sb
          .from('leads')
          .update({ stage, ...(step ?? {}) })
          .eq('id', r.id!)
      }),
    )
    failed += results.filter((res) => res.error).length
  }
  revalidateLead()
  if (failed) return fail(`${failed} of ${ids.length} leads could not be changed. Try again.`)
  return ok(`Moved ${ids.length} ${ids.length === 1 ? 'lead' : 'leads'}`)
}

/** Admin only: assign an owner (or nobody) to the selected leads. */
export async function bulkAssignOwner(input: { ids: string[]; ownerId: string | null }): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = z.object({ ids: Ids, ownerId: z.uuid().nullable() }).safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the selection.')
  const sb = await createClient()
  const { error } = await sb.from('leads').update({ owner_id: parsed.data.ownerId }).in('id', parsed.data.ids)
  if (error) return fail(SAVE_FAILED)
  await Promise.all(parsed.data.ids.map((id) => logActivity(sb, id, user.id, 'edit', { field: 'owner', to: parsed.data.ownerId })))
  revalidateLead()
  return ok('Owner updated')
}

/** Admin only: put the selected leads' primary numbers and domains on the do-not-contact list. */
export async function bulkSuppress(input: { ids: string[] }): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = z.object({ ids: Ids }).safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the selection.')
  const sb = await createClient()
  const { data: rows, error } = await sb.from('v_leads_caller').select('id, phone_e164').in('id', parsed.data.ids)
  if (error) return fail(SAVE_FAILED)
  const phones = [...new Set((rows ?? []).map((r) => r.phone_e164).filter((p): p is string => Boolean(p)))]
  if (!phones.length) return fail('None of these leads has a phone number to block.')
  // The unique index on phone is partial, so skip numbers already listed instead of upserting.
  const { data: existing } = await sb.from('suppression').select('phone_e164').in('phone_e164', phones)
  const listed = new Set((existing ?? []).map((s) => s.phone_e164))
  const fresh = phones.filter((p) => !listed.has(p))
  const { error: insertError } = fresh.length
    ? await sb.from('suppression').insert(fresh.map((p) => ({ phone_e164: p, reason: 'founder_skip', added_by: user.id })))
    : { error: null }
  if (insertError && insertError.code !== '23505') {
    console.error('bulk suppress failed', insertError.code, insertError.message)
    return fail(SAVE_FAILED)
  }
  revalidateLead()
  revalidatePath('/settings/suppression')
  return ok(`${phones.length} ${phones.length === 1 ? 'number' : 'numbers'} added to Do not contact`)
}

const ViewInput = z.object({
  name: z.string().trim().min(1, 'Give the view a name.').max(60, 'Keep the name under 60 characters.'),
  query: z.string().max(2000),
  shared: z.boolean(),
})

export async function saveView(input: z.infer<typeof ViewInput>): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller', 'viewer'])
  const parsed = ViewInput.safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the name.')
  const params = Object.fromEntries(new URLSearchParams(parsed.data.query).entries())
  delete params.page
  const sb = await createClient()
  const { error } = await sb.from('saved_views').insert({
    user_id: user.id,
    name: parsed.data.name,
    query: { qs: new URLSearchParams(parsed.data.query).toString().replace(/(^|&)page=\d+/, ''), params },
    shared: parsed.data.shared,
  })
  if (error) return fail(SAVE_FAILED)
  revalidatePath('/leads')
  return ok('View saved')
}

export async function deleteView(id: string): Promise<ActionResult> {
  await requireRole(['admin', 'caller', 'viewer'])
  const parsed = z.uuid().safeParse(id)
  if (!parsed.success) return fail('View not found.')
  const sb = await createClient()
  const { error } = await sb.from('saved_views').delete().eq('id', parsed.data)
  if (error) return fail(SAVE_FAILED)
  revalidatePath('/leads')
  return ok('View deleted')
}
