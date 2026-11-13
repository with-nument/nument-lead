'use client'

import { useState, useTransition } from 'react'
import { toast } from 'sonner'
import { setDealValue } from '@/app/(app)/leads/[id]/actions'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Select } from '@/components/ui/input'
import { DEAL_CURRENCIES, LOST_REASONS, type DealCurrency, type LeadMoney, type LostReason } from '@/lib/outcomes'

const amountText = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))
const digits = (v: string) => v.replace(/[^\d.]/g, '')

/** Reason menu for Lost and Not now. The first option is a prompt, so nothing is picked by accident. */
export function LostReasonSelect({ id, value, onChange, disabled }: { id?: string; value: string; onChange: (v: LostReason | '') => void; disabled?: boolean }) {
  return (
    <Select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.currentTarget.value as LostReason | '')}>
      <option value="">Choose a reason…</option>
      {LOST_REASONS.map((r) => (
        <option key={r.value} value={r.value}>
          {r.label}
        </option>
      ))}
    </Select>
  )
}

/**
 * Asked when a lead moves to Lost or Not now. Nothing changes until a reason is saved; Cancel leaves the
 * lead where it was.
 */
export function LostReasonDialog({
  target,
  pending,
  onSave,
  onCancel,
}: {
  target: { stage: string; name?: string } | null
  pending?: boolean
  onSave: (reason: LostReason) => void
  onCancel: () => void
}) {
  return (
    <Dialog open={Boolean(target)} onOpenChange={(o) => !o && onCancel()}>
      {target ? <ReasonForm key={`${target.name}-${target.stage}`} target={target} pending={pending} onSave={onSave} onCancel={onCancel} /> : null}
    </Dialog>
  )
}

function ReasonForm({ target, pending, onSave, onCancel }: { target: { stage: string; name?: string }; pending?: boolean; onSave: (reason: LostReason) => void; onCancel: () => void }) {
  const [reason, setReason] = useState<LostReason | ''>('')
  const lost = target.stage === 'lost'
  const why = 'The weekly report counts the reasons, so the engine learns what loses deals.'
  return (
    <DialogContent title={lost ? 'Why was it lost?' : 'Why not now?'} description={target.name ? `Moving ${target.name} to ${lost ? 'Lost' : 'Not now'}. ${why}` : why}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (reason) onSave(reason)
        }}
      >
        <Field label="Reason">{({ id }) => <LostReasonSelect id={id} value={reason} onChange={setReason} />}</Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={pending} disabled={!reason}>
            Save
          </Button>
        </div>
      </form>
    </DialogContent>
  )
}

/**
 * Asked of admins when a lead moves to Won or Retainer: the deal value in rupees and, optionally, what the
 * client pays a month and in which currency. Opens with what is already saved, so nothing is cleared by
 * accident. Only admins see money.
 */
export function DealDialog({ lead, onClose }: { lead: { id: string; name?: string; money?: LeadMoney | null } | null; onClose: () => void }) {
  return (
    <Dialog open={Boolean(lead)} onOpenChange={(o) => !o && onClose()}>
      {lead ? <DealForm key={lead.id} lead={lead} onClose={onClose} /> : null}
    </Dialog>
  )
}

function DealForm({ lead, onClose }: { lead: { id: string; name?: string; money?: LeadMoney | null }; onClose: () => void }) {
  const [deal, setDeal] = useState(amountText(lead.money?.deal))
  const [retainer, setRetainer] = useState(amountText(lead.money?.retainer))
  const [currency, setCurrency] = useState<DealCurrency>(lead.money?.currency ?? 'INR')
  const [pending, start] = useTransition()
  return (
    <DialogContent title={lead.name ? `Deal value for ${lead.name}` : 'Deal value'} description="Only admins see this. You can change it later on the lead page.">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          start(async () => {
            const r = await setDealValue({ leadId: lead.id, value: deal, retainer, currency })
            if (r.ok) {
              toast(r.message ?? 'Saved')
              onClose()
            } else toast.error(r.message)
          })
        }}
      >
        <Field label="Amount (₹)">
          {({ id }) => <Input id={id} inputMode="decimal" value={deal} onChange={(e) => setDeal(digits(e.currentTarget.value))} placeholder="150000" autoFocus />}
        </Field>
        <RetainerFields retainer={retainer} currency={currency} onRetainer={setRetainer} onCurrency={setCurrency} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Later
          </Button>
          <Button type="submit" variant="primary" loading={pending} disabled={!deal && !retainer}>
            Save
          </Button>
        </div>
      </form>
    </DialogContent>
  )
}

/** "Retainer a month (optional)" with its currency beside it. Used by the deal dialog and the Deal card. */
export function RetainerFields({
  retainer,
  currency,
  onRetainer,
  onCurrency,
}: {
  retainer: string
  currency: DealCurrency
  onRetainer: (v: string) => void
  onCurrency: (v: DealCurrency) => void
}) {
  return (
    <div className="flex items-end gap-2">
      <Field label="Retainer a month (optional)" className="min-w-0 flex-1">
        {({ id }) => <Input id={id} inputMode="decimal" value={retainer} onChange={(e) => onRetainer(digits(e.currentTarget.value))} placeholder="40000" />}
      </Field>
      <Field label="Currency" hideLabel className="w-24 shrink-0">
        {({ id }) => (
          <Select id={id} value={currency} onChange={(e) => onCurrency(e.currentTarget.value as DealCurrency)}>
            {DEAL_CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )}
      </Field>
    </div>
  )
}
