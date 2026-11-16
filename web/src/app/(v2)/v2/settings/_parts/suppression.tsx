'use client'

import { useCallback, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { addSuppression, removeSuppression } from '@/app/(app)/settings/suppression/actions'
import { Field, FormError, inputClass, Submit } from '@/app/(v2)/v2/_parts/form'
import { useFormAction, useRun } from '@/app/(v2)/v2/_parts/run'
import { Panel, Row } from '@/app/(v2)/v2/_parts/section'
import { UndoRow } from '@/app/(v2)/v2/_parts/undo-row'
import { IconButton } from '@/app/(v2)/v2/_parts/icon-button'
import { Button } from '@/components/ui2/button'
import { Choice } from '@/app/(v2)/v2/_parts/choice'
import { Select } from '@/components/ui2/select'
import { Sheet, SheetContent } from '@/components/ui2/sheet'
import { toast } from '@/components/ui2/toast'
import { SUPPRESSION_REASONS, SUPPRESSION_REASON_LABEL } from '@/lib/suppression'
import { suppressionInput, type SuppressionEntry } from '../summary'

export type SuppressionView = SuppressionEntry & { label: string; reasonLabel: string; added: string; by: string }

const SHOWN = 6

/** Settings > Do not contact (admins): the count, the newest entries, and the rest one tap away. */
export function SuppressionPanel({ entries, summary }: { entries: SuppressionView[]; summary: string }) {
  const [all, setAll] = useState(false)
  const [removed, setRemoved] = useState<SuppressionView | null>(null)
  const [pending, run] = useRun()
  const clear = useCallback(() => setRemoved(null), [])
  const list = entries.filter((e) => e.id !== removed?.id)
  const shown = all ? list : list.slice(0, SHOWN)
  return (
    <Panel label="Do not contact">
      <Row trailing={<AddSuppressionButton />}>
        <span className="block truncate">
          <span className="font-medium tabular-nums">{entries.length}</span>
          <span className="text-label-3"> {entries.length === 1 ? 'entry' : 'entries'} · {summary}</span>
        </span>
      </Row>
      {removed ? (
        <UndoRow
          message={`Removed ${removed.label}`}
          pending={pending}
          onExpire={clear}
          onUndo={() => {
            const input = suppressionInput(removed)
            if (!input) return
            const fd = new FormData()
            fd.set('kind', input.kind)
            fd.set('value', input.value)
            fd.set('reason', removed.reason)
            run(() => addSuppression(undefined, fd), { quiet: true, onOk: () => (toast('Back on Do not contact'), setRemoved(null)) })
          }}
        />
      ) : null}
      {shown.map((e) => (
        <Row
          key={e.id}
          trailing={
            <IconButton
              aria-label={`Remove ${e.label} from Do not contact`}
              disabled={pending}
              onClick={() => {
                setRemoved(e)
                run(() => removeSuppression(e.id), { quiet: true, onFail: () => setRemoved(null) })
              }}
            >
              <X aria-hidden />
            </IconButton>
          }
        >
          <p className="truncate tabular-nums">{e.label}</p>
          <p className="type-caption truncate text-label-3">
            {e.reasonLabel} · {e.by} · {e.added}
          </p>
        </Row>
      ))}
      {list.length > SHOWN ? (
        <button type="button" onClick={() => setAll((v) => !v)} className="flex min-h-12 w-full items-center px-4 text-left text-[15px] text-label-2 hover:bg-fill-3 lg:px-5 lg:text-[14px]">
          {all ? 'Show fewer' : `Show all ${list.length}`}
        </button>
      ) : null}
    </Panel>
  )
}

const KINDS = [
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone' },
  { value: 'domain', label: 'Website' },
] as const
type Kind = (typeof KINDS)[number]['value']
const PLACEHOLDER: Record<Kind, string> = { email: 'name@company.com', phone: '+91 98110 12345', domain: 'company.com' }

function AddSuppressionButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        <Plus aria-hidden />
        Add
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Add to Do not contact" description="The engine skips them and the app never offers them again.">
          <AddSuppressionForm onDone={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    </>
  )
}

function AddSuppressionForm({ onDone }: { onDone: () => void }) {
  const [kind, setKind] = useState<Kind>('email')
  const [state, action, pending] = useFormAction(addSuppression, onDone)
  return (
    <form action={action} className="flex flex-col gap-4" noValidate>
      <Choice items={KINDS} value={kind} onValueChange={setKind} label="What to add" name="kind" />
      <Field label={KINDS.find((k) => k.value === kind)?.label ?? 'Value'}>
        {({ id }) => (
          <input
            id={id}
            name="value"
            required
            autoComplete="off"
            inputMode={kind === 'phone' ? 'tel' : kind === 'email' ? 'email' : 'url'}
            placeholder={PLACEHOLDER[kind]}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Reason">
        {({ id }) => (
          <Select id={id} name="reason" defaultValue="opt_out" className="w-full">
            {SUPPRESSION_REASONS.map((r) => (
              <option key={r} value={r}>
                {SUPPRESSION_REASON_LABEL[r]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <FormError message={state && !state.ok ? state.message : undefined} />
      <div>
        <Submit pending={pending}>Add</Submit>
      </div>
    </form>
  )
}
