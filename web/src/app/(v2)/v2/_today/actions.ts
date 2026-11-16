'use server'

import { reviewMessage } from '../inbox/actions'
import type { TodayActionResult } from './types'

/**
 * Today's Approve: approves the drafted answer through the Inbox's own action (review_message, migration 0033),
 * so the rules and the activity log are the same. The Undo row waits 30 seconds before calling it, so Undo never
 * has to take an approval back. The engine's outreach run sends the approved email.
 */
export async function approveReply(messageId: string, leadId: string): Promise<TodayActionResult> {
  const res = await reviewMessage({ messageId, leadId, action: 'approve' })
  return res.ok ? { ok: true, message: res.message } : { ok: false, message: res.message }
}
