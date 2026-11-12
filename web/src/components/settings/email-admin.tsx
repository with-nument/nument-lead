'use client'

import { useActionState, useRef, useState, useTransition } from 'react'
import { Send } from 'lucide-react'
import { toast } from 'sonner'
import { addRecipient, removeRecipient, updateRecipient } from '@/app/(app)/settings/email/actions'
import { Tag } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import { Switch } from '@/components/ui/switch'
import type { ActionResult } from '@/lib/action-result'
import { FIELD_LABEL, RECIPIENT_FIELDS, type Recipient, type RecipientField } from '@/lib/notify'

export function AddRecipientForm() {
  const formRef = useRef<HTMLFormElement>(null)
  const [state, action] = useActionState<ActionResult | undefined, FormData>(async (prev, fd) => {
    const r = await addRecipient(prev, fd)
    if (r.ok) {
      toast(r.message ?? 'Added')
      formRef.current?.reset()
    }
    return r
  }, undefined)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form ref={formRef} action={action} className="grid gap-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto] sm:items-start" noValidate>
      <Field label="Email" error={errors?.email ?? (state && !state.ok && !state.fieldErrors ? state.message : undefined)}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="email" type="email" required autoComplete="off" inputMode="email" placeholder="name@nument.in" aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Name" hint="Optional" error={errors?.name}>
        {({ id, describedBy, invalid }) => <Input id={id} name="name" autoComplete="off" placeholder="Aditya" aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
      </Field>
      <SubmitButton className="sm:mt-[26px]">Add</SubmitButton>
    </form>
  )
}

// One fixed template for the header and every row, so the columns line up (table layout from xl).
const ROW_GRID = 'xl:grid-cols-[minmax(0,1fr)_repeat(4,100px)_188px]'

export function RecipientsList({ recipients }: { recipients: Recipient[] }) {
  const [overrides, setOverrides] = useState<Record<string, Partial<Recipient>>>({})
  const [, start] = useTransition()
  if (!recipients.length) {
    return <EmptyState text="Nobody is on the list yet. Until someone is, the engine emails the address in ALERT_EMAIL." />
  }
  const toggle = (r: Recipient, field: RecipientField, value: boolean) => {
    setOverrides((o) => ({ ...o, [r.id]: { ...o[r.id], [field]: value } }))
    start(async () => {
      const res = await updateRecipient({ id: r.id, field, value })
      if (res.ok) return
      toast.error(res.message)
      setOverrides((o) => ({ ...o, [r.id]: { ...o[r.id], [field]: !value } }))
    })
  }
  return (
    <div>
      <div className={`hidden h-10 items-center gap-2 border-b border-line-2 px-5 xl:grid ${ROW_GRID}`} aria-hidden>
        <span className="label-mono">Person</span>
        {RECIPIENT_FIELDS.map((f) => (
          <span key={f} className="label-mono text-center">
            {FIELD_LABEL[f]}
          </span>
        ))}
        <span />
      </div>
      <ul aria-label="Email recipients">
        {recipients.map((base) => {
          const r = { ...base, ...overrides[base.id] }
          const who = r.name ?? r.email
          return (
            <li key={r.id} data-testid="recipient-row" className={`grid gap-3 border-b border-line-2 px-4 py-3.5 last:border-b-0 sm:px-5 xl:items-center xl:gap-2 ${ROW_GRID}`}>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-tx-1">{who}</span>
                  {!r.active ? <Tag tone="warn">Paused</Tag> : null}
                </div>
                {r.name ? <div className="truncate text-sm text-tx-3">{r.email}</div> : null}
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 xl:contents">
                {RECIPIENT_FIELDS.map((f) => (
                  <div key={f} className="flex items-center justify-between gap-3 xl:justify-center">
                    <span className="text-sm text-tx-2 xl:hidden" aria-hidden>
                      {FIELD_LABEL[f]}
                    </span>
                    <Switch checked={r[f]} onCheckedChange={(v) => toggle(r, f, v)} label={`${FIELD_LABEL[f]} for ${r.email}`} />
                  </div>
                ))}
              </div>
              <div className="-ml-3.5 flex items-center gap-1 sm:-ml-3 xl:ml-0 xl:justify-end">
                <SendTestButton id={r.id} email={r.email} />
                <RemoveRecipientButton id={r.id} who={who} />
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function SendTestButton({ id, email }: { id: string; email: string }) {
  const [pending, setPending] = useState(false)
  const send = async () => {
    setPending(true)
    try {
      const res = await fetch('/api/email/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) })
      const body = (await res.json().catch(() => null)) as { ok?: boolean; message?: string } | null
      if (res.ok && body?.ok) toast(body.message ?? 'Test email sent')
      else toast.error(body?.message ?? 'Could not send the test email. Try again.')
    } catch {
      toast.error('Could not reach the server. Try again.')
    } finally {
      setPending(false)
    }
  }
  return (
    <Button size="sm" variant="ghost" loading={pending} onClick={send} aria-label={`Send test email to ${email}`}>
      <Send aria-hidden />
      Send test
    </Button>
  )
}

function RemoveRecipientButton({ id, who }: { id: string; who: string }) {
  const [open, setOpen] = useState(false)
  const [pending, start] = useTransition()
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)} aria-label={`Remove ${who}`}>
        Remove
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Remove from email?" description={`${who} stops getting the morning list, alerts and the weekly report. You can add them again any time.`}>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Keep
            </Button>
            <Button
              variant="danger"
              loading={pending}
              onClick={() =>
                start(async () => {
                  const r = await removeRecipient(id)
                  if (r.ok) {
                    toast(r.message ?? 'Removed')
                    setOpen(false)
                  } else toast.error(r.message)
                })
              }
            >
              Remove
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
