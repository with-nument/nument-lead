'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { fail, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'

// Settings > Sending (new design). The other settings actions live with the classic pages and are reused.

/**
 * Admin only: pauses or resumes all outgoing email (settings `outreach.paused`, read by the engine before every
 * send). The role is checked with the Auth server, and Row Level Security lets only admins change settings.
 */
export async function setOutreachPaused(input: { paused: boolean }): Promise<ActionResult> {
  await requireRole(['admin'], { verified: true })
  const parsed = z.object({ paused: z.boolean() }).safeParse(input)
  if (!parsed.success) return fail('Choose pause or resume.')
  const sb = await createClient()
  const { data, error } = await sb.from('settings').update({ value: parsed.data.paused }).eq('key', 'outreach.paused').select('key')
  if (error) return fail(SAVE_FAILED)
  if (!data?.length) return fail('Sending is not set up yet: the outreach settings are missing.')
  revalidatePath('/settings')
  return ok(parsed.data.paused ? 'All sending paused' : 'Sending resumed')
}
