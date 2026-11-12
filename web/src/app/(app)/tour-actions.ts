'use server'

import { requireUser } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { fail, ok, type ActionResult } from '@/lib/action-result'
import { TOUR_META_KEY } from '@/lib/tour'

/**
 * Remembers that the signed-in user finished or skipped the product tour. Stored in the user's
 * own user_metadata on purpose: it only decides whether the tour opens by itself, so a user
 * editing it changes nothing that matters.
 */
export async function completeTour(): Promise<ActionResult> {
  await requireUser()
  const sb = await createClient()
  const { error } = await sb.auth.updateUser({ data: { [TOUR_META_KEY]: new Date().toISOString() } })
  if (error) return fail('Could not save that the tour is done.')
  return ok()
}
