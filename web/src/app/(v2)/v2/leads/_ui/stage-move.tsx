'use client'

import { useId, useState, useTransition } from 'react'
import { setDealValue, updateStage } from '@/app/(app)/leads/[id]/actions'
import { Button } from '@/components/ui2/button'
import { Select } from '@/components/ui2/select'
import { Sheet, SheetContent } from '@/components/ui2/sheet'
import { toast } from '@/components/ui2/toast'
import { stageLabel } from '@/components/ui2/stage-label'
import { DEAL_CURRENCIES, LOST_REASONS, needsLostReason, type DealCurrency, type LeadMoney, type LostReason } from '@/lib/outcomes'
import { WON_STAGES, type Stage } from '@/lib/stages'
import type { useUndo } from './use-run'

export const fieldClass =
  'h-11 w-full min-w-0 rounded-control bg-fill-1 px-3 text-[17px] text-label-1 outline-none transition-colors hover:bg-fill-2 focus-visible:bg-fill-2 lg:h-9 lg:text-[15px]'

/** Lost and Not now need a reason before anything changes. */
export function ReasonSheet({
  stage,
  name,
  pending,
  onSave,
  onCancel,
}: {
  stage: Stage | null
  name?: string
  pending?: boolean
  onSave: (reason: LostReason) => void
  onCancel: () => void
}) {
  return (
    <Sheet open={Boolean(stage)} onOpenChange={(o) => !o && onCancel()}>
      {stage ? <ReasonForm key={stage} stage={stage} name={name} pending={pending} onSave={onSave} /> : null}
    </Sheet>
  )
}

function ReasonForm({ stage, name, pending, onSave }: { stage: Stage; name?: string; pending?: boolean; onSave: (r: LostReason) => void }) {
  const id = useId()
  const [reason, setReason] = useState<LostReason | ''>('')
  const lost = stage === 'lost'
  return (
    <SheetContent
      title={lost ? 'Why was it lost?' : 'Why not now?'}
      description={`${name ? `Moving ${name} to ${stageLabel(stage)}. ` : ''}The weekly report counts the reasons, so the engine learns what loses deals.`}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (reason) onSave(reason)
        }}
      >
        <label htmlFor={id} className="type-subhead text-label-3">
          Reason
        </label>
        <Select id={id} value={reason} onChange={(e) => setReason(e.currentTarget.value as LostReason | '')}>
          <option value="">Choose a reason…</option>
          {LOST_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </Select>
        <Button type="submit" variant="primary" disabled={!reason || pending}>
          Save
        </Button>
      </form>
    </SheetContent>
  )
}

const amountText = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))
const digits = (v: string) => v.replace(/[^\d.]/g, '')

/** Deal value (rupees), the monthly retainer and its currency. Admins only; used after Won and on the lead. */
export function DealFields({
  leadId,
  money,
  onSaved,
  submitLabel = 'Save',
  autoFocus,
}: {
  leadId: string
  money: LeadMoney | null | undefined
  onSaved?: () => void
  submitLabel?: string
  autoFocus?: boolean
}) {
  const id = useId()
  const saved = { deal: amountText(money?.deal), retainer: amountText(money?.retainer), currency: money?.currency ?? 'INR' }
  const [deal, setDeal] = useState(saved.deal)
  const [retainer, setRetainer] = useState(saved.retainer)
  const [currency, setCurrency] = useState<DealCurrency>(saved.currency)
  const [pending, start] = useTransition()
  const dirty = deal !== saved.deal || retainer !== saved.retainer || currency !== saved.currency
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        start(async () => {
          const r = await setDealValue({ leadId, value: deal, retainer, currency })
          if (r.ok) {
            toast(r.message ?? 'Saved')
            onSaved?.()
          } else toast.error(r.message)
        })
      }}
    >
      <label className="flex flex-col gap-1.5">
        <span className="type-subhead text-label-3">Deal value (₹)</span>
        <input
          id={`${id}-deal`}
          inputMode="decimal"
          autoFocus={autoFocus}
          value={deal}
          onChange={(e) => setDeal(digits(e.currentTarget.value))}
          placeholder="150000"
          className={fieldClass}
        />
      </label>
      <div className="flex items-end gap-2">
        <label className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="type-subhead text-label-3">Retainer a month (optional)</span>
          <input inputMode="decimal" value={retainer} onChange={(e) => setRetainer(digits(e.currentTarget.value))} placeholder="40000" className={fieldClass} />
        </label>
        <Select aria-label="Currency" value={currency} onChange={(e) => setCurrency(e.currentTarget.value as DealCurrency)} className="w-28">
          {DEAL_CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex justify-end">
        <Button type="submit" disabled={!dirty || pending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}

export function DealSheet({ lead, onClose }: { lead: { id: string; name?: string; money?: LeadMoney | null } | null; onClose: () => void }) {
  return (
    <Sheet open={Boolean(lead)} onOpenChange={(o) => !o && onClose()}>
      {lead ? (
        <SheetContent title={lead.name ? `Deal value for ${lead.name}` : 'Deal value'} description="Only admins see this. You can change it later on the lead.">
          <DealFields leadId={lead.id} money={lead.money} onSaved={onClose} autoFocus />
        </SheetContent>
      ) : null}
    </Sheet>
  )
}

/**
 * A stage change with everything it asks for: a reason for Lost and Not now (nothing changes until it is
 * saved), the deal value for admins after Won, an optimistic local stage and an inline Undo.
 */
export function useStageMove({
  isAdmin,
  undo,
  onLocal,
}: {
  isAdmin: boolean
  undo?: ReturnType<typeof useUndo>
  /** Shows the new stage at once (and puts the old one back if the save fails or is undone). */
  onLocal?: (leadId: string, stage: string) => void
}) {
  const [pending, start] = useTransition()
  const [ask, setAsk] = useState<{ leadId: string; from: string; to: Stage; name?: string } | null>(null)
  const [deal, setDeal] = useState<{ id: string; name?: string; money?: LeadMoney | null } | null>(null)

  const commit = (lead: { id: string; stage: string; name?: string; money?: LeadMoney | null; lostReason?: string | null }, to: Stage, reason?: LostReason) => {
    const from = lead.stage
    onLocal?.(lead.id, to)
    start(async () => {
      const r = await updateStage({ leadId: lead.id, stage: to, lostReason: reason })
      if (!r.ok) {
        onLocal?.(lead.id, from)
        toast.error(r.message)
        return
      }
      setAsk(null)
      const back = from as Stage
      const backReason = needsLostReason(back) ? ((lead.lostReason as LostReason | null) ?? 'other') : undefined
      undo?.offer(`${lead.name ? `${lead.name} moved` : 'Moved'} to ${stageLabel(to)}`, async () => {
        onLocal?.(lead.id, from)
        const u = await updateStage({ leadId: lead.id, stage: back, lostReason: backReason })
        if (!u.ok) onLocal?.(lead.id, to)
        return u.ok ? { ok: true, message: `Back to ${stageLabel(back)}` } : u
      })
      if (!undo) toast(`Moved to ${stageLabel(to)}`)
      if (isAdmin && WON_STAGES.includes(to)) setDeal({ id: lead.id, name: lead.name, money: lead.money })
    })
  }

  const move = (lead: { id: string; stage: string; name?: string; money?: LeadMoney | null; lostReason?: string | null }, to: Stage) => {
    if (to === lead.stage) return
    if (needsLostReason(to)) setAsk({ leadId: lead.id, from: lead.stage, to, name: lead.name })
    else commit(lead, to)
  }

  const dialogs = (
    <>
      <ReasonSheet
        stage={ask?.to ?? null}
        name={ask?.name}
        pending={pending}
        onCancel={() => setAsk(null)}
        onSave={(reason) => ask && commit({ id: ask.leadId, stage: ask.from, name: ask.name }, ask.to, reason)}
      />
      <DealSheet lead={deal} onClose={() => setDeal(null)} />
    </>
  )
  return { move, pending, dialogs }
}
