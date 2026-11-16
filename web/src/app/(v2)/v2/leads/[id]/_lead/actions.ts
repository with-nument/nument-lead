'use server'

import type { ActionResult } from '@/lib/action-result'
import { revalidateLead } from '@/lib/revalidate'
import { reviewMessage } from '../../../inbox/actions'

// The lead page's two email writes, through the Inbox's own action (review_message, migration 0033), so the
// rules, the error words and the activity log are the same everywhere. The engine's outreach run sends an
// approved email; until it does, Undo puts the reply back in review.

/** Approves the suggested reply with the person's edits. */
export async function approveReply(input: { leadId: string; messageId: string; body: string }): Promise<ActionResult> {
  const res = await reviewMessage({ messageId: input.messageId, leadId: input.leadId, action: 'approve', body: input.body })
  if (res.ok) revalidateLead(input.leadId)
  return res.ok ? { ok: true, message: res.message } : res
}

/** Undo of an approval that has not gone out yet: back to review. */
export async function reopenReply(input: { leadId: string; messageId: string }): Promise<ActionResult> {
  const res = await reviewMessage({ messageId: input.messageId, leadId: input.leadId, action: 'reopen' })
  if (res.ok) revalidateLead(input.leadId)
  return res.ok ? { ok: true, message: 'Back in review' } : res
}
