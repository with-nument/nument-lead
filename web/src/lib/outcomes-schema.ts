// The server actions' inputs for stage changes, lost reasons and deal money, checked again on the server.
// Server-only on purpose: zod is large, and lib/outcomes.ts (the plain rules and labels) is imported by client
// components, so the schemas live here, where only Server Actions read them.
import 'server-only'
import { z } from 'zod'
import { DEAL_CURRENCIES, LOST_REASON_REQUIRED, LOST_REASON_VALUES, needsLostReason, type DealCurrency } from '@/lib/outcomes'
import { STAGE_VALUES } from '@/lib/stages'

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
