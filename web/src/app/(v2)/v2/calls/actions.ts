'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { logActivity } from '@/lib/activity'
import { fail, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { requireRole } from '@/lib/auth'
import { revalidateLead } from '@/lib/revalidate'
import { createClient } from '@/lib/supabase/server'

// Call notes go into a draft proposal (save_call_notes, migration 0033): the engine's proposals phase writes the
// proposal from them on its next run and the founder reviews it. Stage changes after a call reuse updateStage
// from the lead page actions.

const NotesInput = z.object({
  leadId: z.uuid(),
  notes: z.string().trim().min(1, 'Write a few notes first.').max(8000, 'Keep the notes under 8,000 characters.'),
})

export async function saveCallNotes(input: z.infer<typeof NotesInput>): Promise<ActionResult<{ id: string; drafted: boolean }>> {
  const user = await requireRole(['admin', 'caller'])
  const parsed = NotesInput.safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the notes.')
  const sb = await createClient()
  const { data, error } = await sb.rpc('save_call_notes', { lead_id: parsed.data.leadId, notes: parsed.data.notes })
  if (error) {
    console.error('saveCallNotes failed', error.code, error.message)
    return fail(error.code === 'P0002' ? 'Lead not found.' : SAVE_FAILED)
  }
  const row = (data ?? {}) as Record<string, unknown>
  if (row.created === true) await logActivity(sb, parsed.data.leadId, user.id, 'note', { kind: 'call_notes', proposal_id: String(row.id) })
  revalidatePath('/calls')
  revalidateLead(parsed.data.leadId)
  const drafted = row.drafted === true
  return ok(drafted ? 'Notes saved. The proposal was already drafted; edit it on the lead.' : 'Notes saved. The proposal is drafted on the next engine run.', {
    id: String(row.id ?? ''),
    drafted,
  })
}
