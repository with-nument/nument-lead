'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { logActivity } from '@/lib/activity'
import { fail, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { requireRole } from '@/lib/auth'
import { getInboxPage, type InboxPage } from '@/lib/queries/email'
import { isInboxTab } from '@/lib/queries/email-data'
import { createClient } from '@/lib/supabase/server'

// The Inbox's one write: approve, edit, cancel or reopen an outgoing email through review_message (migration
// 0033), which allows only what the 0022 policy allows and never marks anything sent. The engine's outreach run
// sends an approved email (it checks every gate again first). Rewrite reuses requestRegeneration from the lead page.

const ReviewInput = z.object({
  messageId: z.uuid(),
  leadId: z.uuid(),
  action: z.enum(['approve', 'edit', 'cancel', 'reopen']),
  subject: z.string().max(300).nullish(),
  body: z.string().max(10_000).nullish(),
})

export type ReviewedMessage = { id: string; status: string; subject: string | null; body: string | null }

const DONE: Record<z.infer<typeof ReviewInput>['action'], string> = {
  approve: 'Approved. It goes out with the next send.',
  edit: 'Saved',
  cancel: 'Will not be sent',
  reopen: 'Back in review',
}

export async function reviewMessage(input: z.infer<typeof ReviewInput>): Promise<ActionResult<ReviewedMessage>> {
  const user = await requireRole(['admin', 'caller'])
  const parsed = ReviewInput.safeParse(input)
  if (!parsed.success) return fail('Check the email.')
  const { messageId, leadId, action, subject, body } = parsed.data
  if (body !== undefined && body !== null && !body.trim()) return fail('The email is empty.')
  const sb = await createClient()
  const { data, error } = await sb.rpc('review_message', {
    message_id: messageId,
    action,
    ...(subject !== undefined && subject !== null ? { subject } : {}),
    ...(body !== undefined && body !== null ? { body } : {}),
  })
  if (error) {
    if (error.code === 'P0002') return fail('This email has already gone out or was changed elsewhere. Refresh to see it.')
    console.error('reviewMessage failed', error.code, error.message)
    return fail(SAVE_FAILED)
  }
  const row = (data ?? {}) as Record<string, unknown>
  if (action !== 'reopen') await logActivity(sb, leadId, user.id, 'edit', { field: 'email', action, message_id: messageId })
  revalidatePath('/inbox')
  revalidatePath('/')
  return ok(DONE[action], {
    id: String(row.id ?? messageId),
    status: String(row.status ?? ''),
    subject: typeof row.subject === 'string' ? row.subject : null,
    body: typeof row.body === 'string' ? row.body : null,
  })
}

const Cursor = z.object({ at: z.string().min(1).max(64), id: z.uuid() })

/** The next page of a tab ("Show more"). */
export async function loadInboxPage(tab: string, cursor: { at: string; id: string }): Promise<ActionResult<InboxPage>> {
  await requireRole(['admin', 'caller'])
  const c = Cursor.safeParse(cursor)
  if (!isInboxTab(tab) || !c.success) return fail('Could not load more.')
  try {
    return ok(undefined, await getInboxPage(tab, c.data))
  } catch {
    return fail('Could not load more. Try again.')
  }
}
