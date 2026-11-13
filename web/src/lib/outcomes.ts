// Outcomes the learning loop learns from (migration 0016): what happens when a stage changes, why a
// lead closed, and what a client pays. The lead page, the pipeline board, bulk moves and Replied all
// use these, so they write the same thing. The engine's weekly report counts the reasons.
import { z } from 'zod'
import { istDate } from '@/lib/dates'
import { nextStepAndDue, type StepInput, type StepResult } from '@/lib/next-step'
import { STAGE_VALUES, type Stage } from '@/lib/stages'

/** leads.lost_reason, in the order the menu shows them. */
export const LOST_REASONS = [
  { value: 'price', label: 'Price' },
  { value: 'no_need_now', label: 'No need right now' },
  { value: 'chose_other_vendor', label: 'Chose another vendor' },
  { value: 'no_reply', label: 'No reply' },
  { value: 'not_a_fit', label: 'Not a fit' },
  { value: 'wrong_person', label: 'Wrong person' },
  { value: 'other', label: 'Other' },
] as const
export type LostReason = (typeof LOST_REASONS)[number]['value']
export const LOST_REASON_VALUES = LOST_REASONS.map((r) => r.value) as [LostReason, ...LostReason[]]
export const lostReasonLabel = (v: string | null | undefined) => LOST_REASONS.find((r) => r.value === v)?.label ?? null

/** Lost and Not now need a reason. Any other stage clears it. */
export const REASON_STAGES: readonly Stage[] = ['lost', 'not_now']
export const needsLostReason = (stage: string | null | undefined) => REASON_STAGES.includes(stage as Stage)
export const LOST_REASON_REQUIRED = 'Choose why it closed.'

/** Replied is for a lead that was messaged and has not answered yet. */
export const canMarkReplied = (stage: string | null | undefined) => stage === 'contacted'

/** leads.deal_currency: what the client pays in. The deal value itself stays in rupees. */
export const DEAL_CURRENCIES = ['INR', 'USD', 'AED', 'GBP', 'AUD', 'CAD', 'SGD'] as const
export type DealCurrency = (typeof DEAL_CURRENCIES)[number]
export const isDealCurrency = (v: unknown): v is DealCurrency => DEAL_CURRENCIES.includes(v as DealCurrency)

/** Money on one lead, for admins. */
export type LeadMoney = { deal: number | null; retainer: number | null; currency: DealCurrency }

/** "₹1,50,000" in rupees (lakh grouping), "$1,500" or "AED 5,000" in the client's currency. No conversion. */
export function formatMoney(value: number | null | undefined, currency: string = 'INR') {
  if (value === null || value === undefined) return ''
  const code = isDealCurrency(currency) ? currency : 'INR'
  return new Intl.NumberFormat(code === 'INR' ? 'en-IN' : 'en-US', { style: 'currency', currency: code, maximumFractionDigits: 0 }).format(value)
}

export type StagePatch = { stage: Stage; lost_reason: LostReason | null; wa_at?: string; meeting_at?: string } & Partial<StepResult>

/**
 * What a stage change writes:
 * - Contacted without a first-message date means sent today (the sheet rule, D-043).
 * - Discovery booked without a meeting time sets it to now, so the call has a date to work from.
 * - Lost and Not now carry the reason; any other stage clears an old one.
 * - The next step and due date are worked out again (lib/next-step).
 * Lost or Not now without a reason is refused.
 */
export function stageChange(
  before: StepInput,
  stage: Stage,
  opts: { lostReason?: LostReason | null; now?: Date } = {},
): { ok: true; patch: StagePatch } | { ok: false; message: string } {
  const reason = needsLostReason(stage) ? (opts.lostReason ?? null) : null
  if (needsLostReason(stage) && !reason) return { ok: false, message: LOST_REASON_REQUIRED }
  const now = opts.now ?? new Date()
  const today = istDate(now)
  const patch: StagePatch = { stage, lost_reason: reason }
  if (stage === 'contacted' && !before.wa_at) patch.wa_at = today
  if (stage === 'discovery_booked' && !before.meeting_at) patch.meeting_at = now.toISOString()
  const step = nextStepAndDue({ ...before, ...patch }, today)
  return { ok: true, patch: { ...patch, ...(step ?? {}) } }
}

// Inputs of the server actions, checked again on the server.

const LostReasonField = z.enum(LOST_REASON_VALUES).nullish()
const hasReasonWhenNeeded = (v: { stage: string; lostReason?: string | null }) => !needsLostReason(v.stage) || Boolean(v.lostReason)

export const LeadIds = z.array(z.uuid()).min(1, 'Select at least one lead.').max(200, 'Select at most 200 leads at a time.')

export const StageInput = z
  .object({ leadId: z.uuid(), stage: z.enum(STAGE_VALUES), lostReason: LostReasonField })
  .refine(hasReasonWhenNeeded, { message: LOST_REASON_REQUIRED, path: ['lostReason'] })

export const BulkStageInput = z
  .object({ ids: LeadIds, stage: z.enum(STAGE_VALUES), lostReason: LostReasonField })
  .refine(hasReasonWhenNeeded, { message: LOST_REASON_REQUIRED, path: ['lostReason'] })

export const LostReasonInput = z.object({ leadId: z.uuid(), reason: z.enum(LOST_REASON_VALUES, { error: LOST_REASON_REQUIRED }) })

const Amount = z.union([z.literal(''), z.coerce.number().min(0, 'Use a positive amount.').max(1_000_000_000, 'That amount looks too large.')])

/** The deal form: value in rupees, and optionally the monthly retainer with its currency. */
export const DealInput = z.object({
  leadId: z.uuid(),
  value: Amount,
  retainer: Amount.optional(),
  currency: z.enum(DEAL_CURRENCIES, { error: 'Choose a currency.' }).optional(),
})

const toAmount = (v: '' | number) => (v === '' ? null : Math.round(v * 100) / 100)

/** The money columns a deal form writes; fields it did not send stay as they are. */
export function dealPatch(d: z.infer<typeof DealInput>) {
  const patch: { deal_value_inr: number | null; retainer_monthly_value?: number | null; deal_currency?: DealCurrency } = {
    deal_value_inr: toAmount(d.value),
  }
  if (d.retainer !== undefined) patch.retainer_monthly_value = toAmount(d.retainer)
  if (d.currency !== undefined) patch.deal_currency = d.currency
  return patch
}
