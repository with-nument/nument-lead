'use server'

import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import { logActivity } from '@/lib/activity'
import { fail, fieldErrorsOf, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { istDate } from '@/lib/dates'
import { FEEDBACK_REASONS } from '@/lib/feedback'
import { lintMessage } from '@/lib/lint'
import { nextStepAndDue } from '@/lib/next-step'
import { revalidateLead } from '@/lib/revalidate'
import { STAGE_VALUES } from '@/lib/stages'

// Lead page actions (plan 15.5.4): role check, zod, write as the user (RLS checks again),
// timeline entry, refresh. Stage changes and message edits are logged by the database trigger.

const LeadId = z.uuid()

const StageInput = z.object({ leadId: LeadId, stage: z.enum(STAGE_VALUES) })

export async function updateStage(input: z.infer<typeof StageInput>): Promise<ActionResult> {
  await requireRole(['admin', 'caller'])
  const parsed = StageInput.safeParse(input)
  if (!parsed.success) return fail('Choose a stage.')
  const { leadId, stage } = parsed.data
  const sb = await createClient()
  const { data: before } = await sb
    .from('v_leads_caller')
    .select('stage, wa_at, call_at, d3_at, d7_at, meeting_at')
    .eq('id', leadId)
    .maybeSingle()
  if (!before?.stage) return fail('Lead not found.')
  if (before.stage === stage) return ok()
  const today = istDate()
  // Same rule as the sheet (D-043): Contacted without a first-message date means sent today.
  const wa_at = stage === 'contacted' && !before.wa_at ? today : before.wa_at
  const step = nextStepAndDue({ ...before, stage, wa_at }, today)
  const { error } = await sb
    .from('leads')
    .update({ stage, wa_at, ...(step ?? {}) })
    .eq('id', leadId)
  if (error) {
    console.error('updateStage failed', error.code, error.message)
    return fail(SAVE_FAILED)
  }
  revalidateLead(leadId)
  return ok('Stage updated')
}

const NextStepInput = z.object({
  leadId: LeadId,
  nextStep: z.string().trim().max(120, 'Keep it under 120 characters.'),
  dueAt: z.union([z.iso.date(), z.literal('')]),
})

export async function updateNextStep(input: z.infer<typeof NextStepInput>): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller'])
  const parsed = NextStepInput.safeParse(input)
  if (!parsed.success) return fail('Check the next step.', fieldErrorsOf(parsed.error))
  const { leadId, nextStep, dueAt } = parsed.data
  const sb = await createClient()
  const { error } = await sb
    .from('leads')
    .update({ next_step: nextStep || null, due_at: dueAt || null })
    .eq('id', leadId)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, leadId, user.id, 'edit', { field: 'next_step', next_step: nextStep || null, due_at: dueAt || null })
  revalidateLead(leadId)
  return ok('Next step saved')
}

export async function updateOwner(input: { leadId: string; ownerId: string | null }): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = z.object({ leadId: LeadId, ownerId: z.uuid().nullable() }).safeParse(input)
  if (!parsed.success) return fail('Choose an owner.')
  const sb = await createClient()
  const { error } = await sb.from('leads').update({ owner_id: parsed.data.ownerId }).eq('id', parsed.data.leadId)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, parsed.data.leadId, user.id, 'edit', { field: 'owner', to: parsed.data.ownerId })
  revalidateLead(parsed.data.leadId)
  return ok('Owner updated')
}

const MessageField = z.enum(['message', 'message_alt', 'followup_d3', 'followup_d7'])
const MessageInput = z.object({ leadId: LeadId, field: MessageField, text: z.string().max(2000) })

/** Saves a message. The lint is checked here too, so a message with problems is never stored. */
export async function saveMessage(input: z.infer<typeof MessageInput>): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller'])
  const parsed = MessageInput.safeParse(input)
  if (!parsed.success) return fail('Check the message.')
  const { leadId, field } = parsed.data
  const text = parsed.data.text.trim()
  const problems = text ? lintMessage(text, field) : []
  if (problems.length) return fail(`Fix this first: ${problems.join('; ')}.`)
  const sb = await createClient()
  const patch =
    field === 'message'
      ? { message: text || null }
      : field === 'message_alt'
        ? { message_alt: text || null }
        : field === 'followup_d3'
          ? { followup_d3: text || null }
          : { followup_d7: text || null }
  const { error } = await sb.from('leads').update(patch).eq('id', leadId)
  if (error) return fail(SAVE_FAILED)
  // message and message_alt edits are logged by the trigger as message_edited; follow-ups are logged here.
  if (field === 'followup_d3' || field === 'followup_d7') await logActivity(sb, leadId, user.id, 'edit', { field })
  revalidateLead(leadId)
  return ok('Message saved')
}

/** Swaps the main and alternate messages. */
export async function switchToAlternate(leadId: string): Promise<ActionResult> {
  await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  if (!id.success) return fail('Lead not found.')
  const sb = await createClient()
  const { data } = await sb.from('v_leads_caller').select('message, message_alt').eq('id', id.data).maybeSingle()
  if (!data?.message_alt) return fail('There is no alternate message for this lead.')
  const { error } = await sb.from('leads').update({ message: data.message_alt, message_alt: data.message }).eq('id', id.data)
  if (error) return fail(SAVE_FAILED)
  revalidateLead(id.data)
  return ok('Switched to the alternate message')
}

/** Asks the morning run to write a new message (plan 12, regen_requested_at). */
export async function requestRegeneration(leadId: string): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller'])
  const id = LeadId.safeParse(leadId)
  if (!id.success) return fail('Lead not found.')
  const sb = await createClient()
  const { error } = await sb.from('leads').update({ regen_requested_at: new Date().toISOString() }).eq('id', id.data)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, id.data, user.id, 'regen_request')
  revalidateLead(id.data)
  return ok('New message requested. The morning run writes it.')
}

const NoteInput = z.object({ leadId: LeadId, text: z.string().trim().min(1, 'Write a note first.').max(1000, 'Keep notes under 1,000 characters.') })

/** Adds a note to the timeline. The newest note is also the summary the sheet shows in Notes. */
export async function addNote(input: z.infer<typeof NoteInput>): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller'])
  const parsed = NoteInput.safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the note.')
  const sb = await createClient()
  const { error } = await sb.from('leads').update({ notes: parsed.data.text }).eq('id', parsed.data.leadId)
  if (error) return fail(SAVE_FAILED)
  await logActivity(sb, parsed.data.leadId, user.id, 'note', { text: parsed.data.text })
  revalidateLead(parsed.data.leadId)
  return ok('Note added')
}

const DealInput = z.object({
  leadId: LeadId,
  value: z.union([z.literal(''), z.coerce.number().min(0, 'Use a positive amount.').max(1_000_000_000, 'That amount looks too large.')]),
})

/**
 * Admin only. Deal value has no column grant for app users, so it is written with the service role
 * after the role check (plan 2.8.3). The timeline records that it changed, never the amount, because
 * callers can read the timeline.
 */
export async function setDealValue(input: { leadId: string; value: string }): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = DealInput.safeParse(input)
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? 'Check the amount.')
  const value = parsed.data.value === '' ? null : Math.round(parsed.data.value * 100) / 100
  const admin = createAdminClient()
  const { error } = await admin.from('leads').update({ deal_value_inr: value }).eq('id', parsed.data.leadId)
  if (error) return fail(SAVE_FAILED)
  const sb = await createClient()
  await logActivity(sb, parsed.data.leadId, user.id, 'edit', { field: 'deal_value' })
  revalidateLead(parsed.data.leadId)
  return ok('Deal value saved')
}

const ALLOWED_TYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
])
const MAX_BYTES = 10 * 1024 * 1024

/** Admin only: proposal upload to the private `proposals` bucket (PDF or DOCX, up to 10 MB). */
export async function uploadProposal(leadId: string, formData: FormData): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const id = LeadId.safeParse(leadId)
  if (!id.success) return fail('Lead not found.')
  const file = formData.get('file')
  if (!(file instanceof File) || file.size === 0) return fail('Choose a PDF or Word file.')
  if (file.size > MAX_BYTES) return fail('Choose a file under 10 MB.')
  if (!ALLOWED_TYPES.has(file.type)) return fail('Only PDF and Word (.docx) files can be uploaded.')
  const safeName = file.name.replace(/[^\w.-]/g, '_').slice(-120)
  const path = `${id.data}/${Date.now()}-${safeName}`
  const sb = await createClient()
  const { error } = await sb.storage.from('proposals').upload(path, file, { contentType: file.type, upsert: false })
  if (error) {
    console.error('proposal upload failed', error.message)
    return fail('Upload failed. Try again.')
  }
  await logActivity(sb, id.data, user.id, 'proposal_upload', { file: safeName })
  revalidateLead(id.data)
  return ok('Proposal uploaded')
}

/** A 60-second signed link to download a proposal. */
export async function proposalLink(path: string): Promise<ActionResult<string>> {
  await requireRole(['admin'])
  const valid = z
    .string()
    .regex(/^[0-9a-f-]{36}\/[\w.-]+$/i)
    .safeParse(path)
  if (!valid.success) return fail('File not found.')
  const sb = await createClient()
  const { data, error } = await sb.storage.from('proposals').createSignedUrl(valid.data, 60, { download: true })
  if (error || !data) return fail('Could not open the file.')
  return ok(undefined, data.signedUrl)
}


const FeedbackInput = z.object({ leadId: LeadId, rating: z.union([z.literal(1), z.literal(-1)]), reason: z.enum(FEEDBACK_REASONS) })

/** Thumbs up or down with a reason. One per person per lead; a new vote replaces the old one. */
export async function sendFeedback(input: z.infer<typeof FeedbackInput>): Promise<ActionResult> {
  const user = await requireRole(['admin', 'caller', 'viewer'])
  const parsed = FeedbackInput.safeParse(input)
  if (!parsed.success) return fail('Choose a reason.')
  const { leadId, rating, reason } = parsed.data
  const sb = await createClient()
  const { error } = await sb
    .from('feedback')
    .upsert({ lead_id: leadId, user_id: user.id, rating, reason, at: new Date().toISOString() }, { onConflict: 'lead_id,user_id' })
  if (error) {
    console.error('feedback failed', error.code, error.message)
    return fail(SAVE_FAILED)
  }
  // Viewers can vote but cannot write the timeline (RLS); admins and callers log it.
  if (user.role !== 'viewer') await logActivity(sb, leadId, user.id, 'feedback', { rating, reason })
  revalidateLead(leadId)
  return ok('Thanks, feedback saved')
}
