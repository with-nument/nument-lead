'use client'

import { useState, useTransition } from 'react'
import { toast } from 'sonner'
import { setDealValue, updateNextStep, updateOwner, updateStage } from '@/app/(app)/leads/[id]/actions'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Select } from '@/components/ui/input'
import { STAGES, WON_STAGES, type Stage } from '@/lib/stages'

function useAction() {
  const [pending, start] = useTransition()
  const run = (fn: () => Promise<{ ok: boolean; message?: string }>, onOk?: () => void) =>
    start(async () => {
      const r = await fn()
      if (r.ok) {
        if (r.message) toast(r.message)
        onOk?.()
      } else toast.error(r.message ?? 'Could not save. Try again.')
    })
  return { pending, run }
}

/** Stage dropdown. An admin moving a lead to Won or Retainer is asked for the deal value. */
export function StageSelect({ leadId, stage, isAdmin }: { leadId: string; stage: string; isAdmin: boolean }) {
  const { pending, run } = useAction()
  const [value, setValue] = useState(stage)
  const [askDeal, setAskDeal] = useState(false)
  const [deal, setDeal] = useState('')
  return (
    <>
      <div className="w-full sm:w-52">
        <label htmlFor="lead-stage" className="label-mono mb-1 block">
          Stage
        </label>
        <Select
          id="lead-stage"
          value={value}
          disabled={pending}
          onChange={(e) => {
            const next = e.currentTarget.value as Stage
            const prev = value
            setValue(next)
            run(
              async () => {
                const r = await updateStage({ leadId, stage: next })
                if (!r.ok) setValue(prev)
                return r
              },
              () => {
                if (isAdmin && WON_STAGES.includes(next)) setAskDeal(true)
              },
            )
          }}
        >
          {STAGES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
      </div>
      <Dialog open={askDeal} onOpenChange={setAskDeal}>
        <DialogContent title="Deal value" description="Record what this client is worth, in rupees. Only admins see this.">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              run(() => setDealValue({ leadId, value: deal }), () => setAskDeal(false))
            }}
          >
            <Field label="Amount (₹)">
              {({ id }) => <Input id={id} inputMode="decimal" value={deal} onChange={(e) => setDeal(e.currentTarget.value.replace(/[^\d.]/g, ''))} placeholder="150000" autoFocus />}
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setAskDeal(false)}>
                Later
              </Button>
              <Button type="submit" variant="primary" loading={pending}>
                Save
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function OwnerSelect({ leadId, ownerId, team }: { leadId: string; ownerId: string | null; team: { id: string; name: string }[] }) {
  const { pending, run } = useAction()
  const [value, setValue] = useState(ownerId ?? '')
  return (
    <div className="w-full sm:w-48">
      <label htmlFor="lead-owner" className="label-mono mb-1 block">
        Owner
      </label>
      <Select
        id="lead-owner"
        value={value}
        disabled={pending}
        onChange={(e) => {
          const next = e.currentTarget.value
          setValue(next)
          run(() => updateOwner({ leadId, ownerId: next || null }))
        }}
      >
        <option value="">Nobody yet</option>
        {team.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </Select>
    </div>
  )
}

export function NextStepEditor({ leadId, nextStep, dueAt }: { leadId: string; nextStep: string | null; dueAt: string | null }) {
  const { pending, run } = useAction()
  const [step, setStep] = useState(nextStep ?? '')
  const [due, setDue] = useState(dueAt ?? '')
  const dirty = step !== (nextStep ?? '') || due !== (dueAt ?? '')
  return (
    <form
      className="flex w-full flex-wrap items-end gap-2 sm:w-auto"
      onSubmit={(e) => {
        e.preventDefault()
        run(() => updateNextStep({ leadId, nextStep: step, dueAt: due }))
      }}
    >
      <div className="min-w-0 flex-1 sm:w-56 sm:flex-none">
        <label htmlFor="lead-next" className="label-mono mb-1 block">
          Next step
        </label>
        <Input id="lead-next" value={step} maxLength={120} onChange={(e) => setStep(e.currentTarget.value)} placeholder="Book discovery call" />
      </div>
      <div className="w-40">
        <label htmlFor="lead-due" className="label-mono mb-1 block">
          Due
        </label>
        <Input id="lead-due" type="date" value={due} onChange={(e) => setDue(e.currentTarget.value)} />
      </div>
      {dirty ? (
        <Button type="submit" variant="primary" loading={pending}>
          Save
        </Button>
      ) : null}
    </form>
  )
}
