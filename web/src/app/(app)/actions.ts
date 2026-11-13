'use server'

import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient, type ServerClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import { logActivity } from '@/lib/activity'
import { fail, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { istDate } from '@/lib/dates'
import { nextStepAndDue } from '@/lib/next-step'
import { canMarkReplied, stageChange } from '@/lib/outcomes'
import { STAGE_VALUES, stageOf } from '@/lib/stages'
import { revalidateLead } from '@/lib/revalidate'

// Today's one-tap actions (plan 15.6.3). Each one: check the role, validate, write as the user
// (RLS checks again), log the activity, refresh the pages that show the lead.

const LeadId = z.uuid()
const Channel = z.enum(['web', 'app', 'manual', 'call', 'email'])

const Previous = z.object({
  stage: z.enum(STAGE_VALUES),
  wa_at: z.iso.date().nullable(),
  skipped_until: z.string().max(40).nullable(),
  next_step: z.string().max(200).nullable(),
  due_at: z.iso.date().nullable(),
})
export type PreviousState = z.infer<typeof Previous>

const STATE_COLUMNS = 'stage, wa_at, call_at, d3_at, d7_at, meeting_at, skipped_until, next_step, due_at, phone_e164' as const

async function readState(sb: ServerClient, leadId: string) {
  const { data } = await sb.from('v_leads_caller').select(STATE_COLUMNS).eq('id', leadId).maybeSingle()
  if (!data?.stage) return null
  const previous: PreviousState = {
    stage: data.stage as PreviousState['stage'],
    wa_at: data.wa_at,
    skipped_until: data.skipped_until,
    next_step: data.next_step,
    due_at: data.due_at,
  }
  return { row: { ...data, stage: data.stage }, previous }
}

/** First message sent: stage Contacted (if it was New), wa_at today in India, a `sent` activity. */
export async function markContacted(leadId: string, channel: z.infer<typeof Channel>): Promise<ActionResult<PreviousState>> {
  const user = await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  const ch = Channel.safeParse(channel)
  if (!id.success || !ch.success) return fail('Lead not found.')
  const sb = await createClient()
  const state = await readState(sb, id.data)
  if (!state) return fail('Lead not found.')
  const today = istDate()
  const stage = state.row.stage === 'new' ? 'contacted' : state.row.stage
  const wa_at = state.row.wa_at ?? today
  const step = nextStepAndDue({ ...state.row, stage, wa_at }, today)
  const { error } = await sb
    .from('leads')
    .update({ stage, wa_at, skipped_until: null, ...(step ?? {}) })
    .eq('id', id.data)
  if (error) {
    console.error('markContacted failed', error.code, error.message)
    return fail(SAVE_FAILED)
  }
  await logActivity(sb, id.data, user.id, 'sent', { channel: ch.data })
  revalidateLead(id.data)
  return ok('Marked as contacted', state.previous)
}

/**
 * They answered: Contacted to Talking in one tap, a `reply` on the timeline (the trigger logs the stage
 * change), next step "Book discovery call". Only from Contacted, so a later stage is never moved back.
 */
export async function markReplied(leadId: string): Promise<ActionResult<PreviousState>> {
  const user = await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  if (!id.success) return fail('Lead not found.')
  const sb = await createClient()
  const state = await readState(sb, id.data)
  if (!state) return fail('Lead not found.')
  if (!canMarkReplied(state.row.stage)) return fail(`This lead is at ${stageOf(state.row.stage).label}, so there is no reply to mark.`)
  const change = stageChange(state.row, 'talking')
  if (!change.ok) return fail(change.message)
  const { error } = await sb.from('leads').update(change.patch).eq('id', id.data)
  if (error) {
    console.error('markReplied failed', error.code, error.message)
    return fail(SAVE_FAILED)
  }
  await logActivity(sb, id.data, user.id, 'reply')
  revalidateLead(id.data)
  return ok('Marked as replied', state.previous)
}

/** Hide a lead from Today for 7 days. */
export async function skipLead(leadId: string): Promise<ActionResult<PreviousState>> {
  const user = await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  if (!id.success) return fail('Lead not found.')
  const sb = await createClient()
  const state = await readState(sb, id.data)
  if (!state) return fail('Lead not found.')
  const until = new Date(Date.now() + 7 * 86_400_000).toISOString()
  const { error } = await sb.from('leads').update({ skipped_until: until }).eq('id', id.data)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, id.data, user.id, 'skip', { until })
  revalidateLead(id.data)
  return ok('Skipped for 7 days', state.previous)
}

/**
 * Wrong number: stage Wrong contact, the number goes on Do not contact and every contact with that
 * number is flagged, so the engine never offers it again.
 */
export async function markWrongContact(leadId: string): Promise<ActionResult<PreviousState>> {
  const user = await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  if (!id.success) return fail('Lead not found.')
  const sb = await createClient()
  const state = await readState(sb, id.data)
  if (!state) return fail('Lead not found.')
  const step = nextStepAndDue({ ...state.row, stage: 'wrong_contact' }, istDate())
  const { error } = await sb
    .from('leads')
    .update({ stage: 'wrong_contact', ...(step ?? {}) })
    .eq('id', id.data)
  if (error) {
    console.error('markWrongContact failed', error.code, error.message)
    return fail(SAVE_FAILED)
  }
  const phone = state.row.phone_e164
  if (phone) {
    const flag = await sb.from('contacts').update({ do_not_contact: true }).eq('phone_e164', phone)
    if (flag.error) console.error('contact flag failed', flag.error.code, flag.error.message)
    const block = await sb.from('suppression').insert({ phone_e164: phone, reason: 'wrong_contact', added_by: user.id })
    // 23505: the number is already on the list, which is the goal.
    if (block.error && block.error.code !== '23505') console.error('suppression insert failed', block.error.code, block.error.message)
  }
  await logActivity(sb, id.data, user.id, 'wrong_contact', { phone, reason: 'wrong_contact' })
  revalidateLead(id.data)
  return ok('Marked as wrong contact', state.previous)
}

const UNDO_WINDOW_MS = 15 * 60_000

export type UndoKind = 'sent' | 'replied' | 'skip' | 'wrong_contact'
const UndoKinds = z.enum(['sent', 'replied', 'skip', 'wrong_contact'])

/**
 * Undo for Mark sent, Replied, Skip and Wrong contact (toast button). Restores the earlier stage, dates and
 * next step. For a wrong contact it also lifts the do-not-contact mark, but only when this user made
 * that mark on this lead in the last 15 minutes (read from the timeline, never from the browser).
 */
export async function undoLeadChange(
  leadId: string,
  previousInput: PreviousState,
  kind: UndoKind,
): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  const previous = Previous.safeParse(previousInput)
  if (!id.success || !previous.success || !UndoKinds.safeParse(kind).success) return fail('Nothing to undo.')
  const sb = await createClient()

  if (kind === 'wrong_contact') {
    const { data: last } = await sb
      .from('activities')
      .select('user_id, at, payload')
      .eq('lead_id', id.data)
      .eq('type', 'wrong_contact')
      .order('at', { ascending: false })
      .limit(1)
      .maybeSingle()
    const fresh = last && last.user_id === user.id && Date.now() - Date.parse(last.at) < UNDO_WINDOW_MS
    if (!last || !fresh) return fail('This can no longer be undone here. Ask an admin to remove the number from Do not contact.')
    const phone = (last.payload as { phone?: string | null } | null)?.phone ?? null
    if (phone) {
      await sb.from('contacts').update({ do_not_contact: false }).eq('phone_e164', phone)
      // Only admins may delete from Do not contact under RLS. The checks above limit this
      // service-role delete to the entry this user just made for this lead.
      const admin = createAdminClient()
      const since = new Date(Date.parse(last.at) - 60_000).toISOString()
      await admin
        .from('suppression')
        .delete()
        .eq('phone_e164', phone)
        .eq('reason', 'wrong_contact')
        .eq('added_by', user.id)
        .gte('added_at', since)
    }
  }

  const { error } = await sb.from('leads').update(previous.data).eq('id', id.data)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, id.data, user.id, 'undo', { undid: kind })
  revalidateLead(id.data)
  return ok('Undone')
}

const Followup = z.object({ leadId: z.uuid(), which: z.enum(['d3', 'd7']), channel: Channel })

/** Day 3 or day 7 follow-up sent: sets d3_at or d7_at to today, updates the next step, logs it. */
export async function markFollowupSent(input: z.infer<typeof Followup>): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller'])
  const parsed = Followup.safeParse(input)
  if (!parsed.success) return fail('Lead not found.')
  const { leadId, which, channel } = parsed.data
  const sb = await createClient()
  const state = await readState(sb, leadId)
  if (!state) return fail('Lead not found.')
  const today = istDate()
  const dates = which === 'd3' ? { d3_at: state.row.d3_at ?? today } : { d7_at: state.row.d7_at ?? today }
  const step = nextStepAndDue({ ...state.row, ...dates }, today)
  const { error } = await sb
    .from('leads')
    .update({ ...dates, ...(step ?? {}) })
    .eq('id', leadId)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, leadId, user.id, 'followup_sent', { which, channel })
  revalidateLead(leadId)
  return ok(which === 'd3' ? 'Day 3 follow-up marked as sent' : 'Day 7 follow-up marked as sent')
}
