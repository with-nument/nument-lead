import 'server-only'
import type { Json } from '@/lib/database.types'
import type { ServerClient } from '@/lib/supabase/server'

/**
 * Activity types the app writes itself. Stage changes, grade changes and message edits are
 * logged by the database trigger (leads_after_write), so the app never logs those twice.
 */
export type AppActivityType =
  | 'sent'
  | 'followup_sent'
  | 'edit'
  | 'note'
  | 'skip'
  | 'wrong_contact'
  | 'feedback'
  | 'proposal_upload'
  | 'regen_request'
  | 'undo'

/** Writes one timeline row (source "app") and bumps the lead's last activity time. */
export async function logActivity(
  sb: ServerClient,
  leadId: string,
  userId: string,
  type: AppActivityType,
  payload: Record<string, Json | undefined> = {},
) {
  const now = new Date().toISOString()
  const { error } = await sb
    .from('activities')
    .insert({ lead_id: leadId, user_id: userId, source: 'app', type, payload: payload as Json, at: now })
  if (error) console.error('activity insert failed', { leadId, type, code: error.code, message: error.message })
  await sb.from('leads').update({ last_activity_at: now }).eq('id', leadId)
}
