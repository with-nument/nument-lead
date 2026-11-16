'use client'

import { useCallback, useState } from 'react'
import { Check, Ellipsis, Plus } from 'lucide-react'
import { addRecipient, removeRecipient, updateRecipient } from '@/app/(app)/settings/email/actions'
import { Field, FormError, inputClass, Submit } from '@/app/(v2)/v2/_parts/form'
import { useFormAction, useRun } from '@/app/(v2)/v2/_parts/run'
import { Panel, Row } from '@/app/(v2)/v2/_parts/section'
import { UndoRow } from '@/app/(v2)/v2/_parts/undo-row'
import { IconButton } from '@/app/(v2)/v2/_parts/icon-button'
import { Button } from '@/components/ui2/button'
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { Sheet, SheetContent } from '@/components/ui2/sheet'
import { toast } from '@/components/ui2/toast'
import { FIELD_LABEL, NOTIFY_KINDS, NOTIFY_KIND_HINT, NOTIFY_KIND_LABEL, RECIPIENT_FIELDS, type Recipient, type RecipientField } from '@/lib/notify'
import { recipientSummary } from '../summary'

/** Settings > Email recipients (admins): who gets the morning list, alerts and the weekly report. */
export function RecipientsPanel({ recipients }: { recipients: Recipient[] }) {
  const [overrides, setOverrides] = useState<Record<string, Partial<Recipient>>>({})
  const [removed, setRemoved] = useState<Recipient | null>(null)
  const [pending, run] = useRun()
  const clear = useCallback(() => setRemoved(null), [])
  const list = recipients.map((r) => ({ ...r, ...overrides[r.id] }))

  const toggle = (r: Recipient, field: RecipientField) => {
    const value = !r[field]
    setOverrides((o) => ({ ...o, [r.id]: { ...o[r.id], [field]: value } }))
    run(() => updateRecipient({ id: r.id, field, value }), { onFail: () => setOverrides((o) => ({ ...o, [r.id]: { ...o[r.id], [field]: !value } })) })
  }

  return (
    <Panel label="Email recipients">
      {list.length === 0 && !removed ? (
        <Row>
          <span className="block text-label-3">Nobody yet. Until someone is added, the engine emails the address in ALERT_EMAIL.</span>
        </Row>
      ) : null}
      {list.map((r) =>
        removed?.id === r.id ? null : (
          <Row
            key={r.id}
            trailing={
              <Menu>
                <MenuTrigger asChild>
                  <IconButton aria-label={`Emails for ${r.email}`}>
                    <Ellipsis aria-hidden />
                  </IconButton>
                </MenuTrigger>
                <MenuContent>
                  {RECIPIENT_FIELDS.map((f) => (
                    <MenuItem
                      key={f}
                      onSelect={(e) => {
                        e.preventDefault()
                        toggle(r, f)
                      }}
                    >
                      {r[f] ? <Check aria-hidden /> : <span aria-hidden className="size-4" />}
                      <span className="flex-1">{FIELD_LABEL[f]}</span>
                    </MenuItem>
                  ))}
                  <MenuSeparator />
                  <MenuItem
                    destructive
                    onSelect={() => {
                      setRemoved(r)
                      run(() => removeRecipient(r.id), { quiet: true, onFail: () => setRemoved(null) })
                    }}
                  >
                    Remove
                  </MenuItem>
                </MenuContent>
              </Menu>
            }
          >
            <p className="truncate">
              <span className="font-medium">{r.name || r.email}</span>
              {r.name ? <span className="text-label-3"> · {r.email}</span> : null}
            </p>
            <p className="type-caption truncate text-label-3">{recipientSummary(r)}</p>
          </Row>
        ),
      )}
      {removed ? (
        <UndoRow
          message={`Removed ${removed.email}`}
          pending={pending}
          onExpire={clear}
          onUndo={() => {
            const fd = new FormData()
            fd.set('email', removed.email)
            fd.set('name', removed.name ?? '')
            run(() => addRecipient(undefined, fd), { quiet: true, onOk: () => (toast('Put back: gets every email again'), setRemoved(null)) })
          }}
        />
      ) : null}
    </Panel>
  )
}

/** The Add button beside the title and its sheet. */
export function AddRecipientButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        <Plus aria-hidden />
        Add
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Add a recipient" description="New people get every email. Switch any of them off from the list.">
          <AddRecipientForm onDone={() => setOpen(false)} />
          <ul className="mt-6 flex flex-col gap-2">
            {NOTIFY_KINDS.map((k) => (
              <li key={k} className="type-subhead text-label-3">
                <span className="font-medium text-label-2">{NOTIFY_KIND_LABEL[k]}</span>: {NOTIFY_KIND_HINT[k]}
              </li>
            ))}
          </ul>
        </SheetContent>
      </Sheet>
    </>
  )
}

function AddRecipientForm({ onDone }: { onDone: () => void }) {
  const [state, action, pending] = useFormAction(addRecipient, onDone)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="flex flex-col gap-4" noValidate>
      <Field label="Email" error={errors?.email}>
        {({ id, describedBy, invalid }) => (
          <input id={id} name="email" type="email" inputMode="email" autoComplete="off" required placeholder="name@nument.in" className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Name" hint="Optional" error={errors?.name}>
        {({ id, describedBy, invalid }) => <input id={id} name="name" autoComplete="off" className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
      </Field>
      <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
      <div>
        <Submit pending={pending}>Add</Submit>
      </div>
    </form>
  )
}
