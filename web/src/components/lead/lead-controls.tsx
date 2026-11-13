'use client'

import { useState, useTransition } from 'react'
import { MessageCircleReply } from 'lucide-react'
import { toast } from 'sonner'
import { setLostReason, updateNextStep, updateOwner, updateStage } from '@/app/(app)/leads/[id]/actions'
import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/input'
import { canMarkReplied, needsLostReason, type LeadMoney, type LostReason } from '@/lib/outcomes'
import { STAGES, WON_STAGES, type Stage } from '@/lib/stages'
import { DealDialog, LostReasonDialog, LostReasonSelect } from './outcome-dialogs'
import { useLeadActions } from './use-lead-actions'

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

/**
 * Stage menu and what each stage asks for:
 * - Contacted: a Replied button beside it, one tap to Talking.
 * - Lost or Not now: the reason first (nothing changes until it is saved), then a Reason menu beside the
 *   stage to correct it or fill it in for a lead closed in the sheet.
 * - Won or Retainer, for admins: the deal value and the monthly retainer.
 */
export function StageSelect({
  leadId,
  stage,
  lostReason,
  isAdmin,
  money,
}: {
  leadId: string
  stage: string
  lostReason: string | null
  isAdmin: boolean
  money?: LeadMoney | null
}) {
  const { pending, run } = useAction()
  const leadActions = useLeadActions()
  const [value, setValue] = useState(stage)
  const [synced, setSynced] = useState(stage)
  if (synced !== stage) {
    // The server moved the lead (Replied, Undo, another tab): show its stage.
    setSynced(stage)
    setValue(stage)
  }
  const [askReason, setAskReason] = useState<Stage | null>(null)
  const [askDeal, setAskDeal] = useState(false)

  const move = (next: Stage, reason?: LostReason) => {
    const prev = value
    setValue(next)
    run(
      async () => {
        const r = await updateStage({ leadId, stage: next, lostReason: reason })
        if (!r.ok) setValue(prev)
        return r
      },
      () => {
        setAskReason(null)
        if (isAdmin && WON_STAGES.includes(next)) setAskDeal(true)
      },
    )
  }

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
            if (needsLostReason(next)) setAskReason(next)
            else move(next)
          }}
        >
          {STAGES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
      </div>
      {canMarkReplied(stage) ? (
        <Button variant="secondary" loading={leadActions.pending} disabled={pending} onClick={() => leadActions.replied(leadId)} title="They answered: move to Talking">
          <MessageCircleReply aria-hidden />
          Replied
        </Button>
      ) : null}
      {needsLostReason(stage) ? <ReasonSelect key={lostReason ?? ''} leadId={leadId} reason={lostReason} /> : null}
      <LostReasonDialog target={askReason ? { stage: askReason } : null} pending={pending} onSave={(reason) => askReason && move(askReason, reason)} onCancel={() => setAskReason(null)} />
      <DealDialog lead={askDeal ? { id: leadId, money } : null} onClose={() => setAskDeal(false)} />
    </>
  )
}

/** Why a Lost or Not now lead closed, changeable in place. */
function ReasonSelect({ leadId, reason }: { leadId: string; reason: string | null }) {
  const { pending, run } = useAction()
  const [value, setValue] = useState(reason ?? '')
  return (
    <div className="w-full sm:w-52">
      <label htmlFor="lead-lost-reason" className="label-mono mb-1 block">
        Reason
      </label>
      <LostReasonSelect
        id="lead-lost-reason"
        value={value}
        disabled={pending}
        onChange={(next) => {
          if (!next) return
          const prev = value
          setValue(next)
          run(async () => {
            const r = await setLostReason({ leadId, reason: next })
            if (!r.ok) setValue(prev)
            return r
          })
        }}
      />
    </div>
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
