'use client'

import { useActionState, useRef, useState, useTransition } from 'react'
import { toast } from 'sonner'
import { addSuppression, removeSuppression } from '@/app/(app)/settings/suppression/actions'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Select } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import type { ActionResult } from '@/lib/action-result'
import { SUPPRESSION_REASONS, SUPPRESSION_REASON_LABEL } from '@/lib/suppression'

export function AddSuppressionForm() {
  const formRef = useRef<HTMLFormElement>(null)
  const [state, action] = useActionState<ActionResult | undefined, FormData>(async (prev, fd) => {
    const r = await addSuppression(prev, fd)
    if (r.ok) {
      toast(r.message ?? 'Added')
      formRef.current?.reset()
    }
    return r
  }, undefined)
  return (
    <form ref={formRef} action={action} className="grid gap-3 sm:grid-cols-[140px_minmax(0,1fr)_200px_auto] sm:items-end">
      <Field label="Type">
        {({ id }) => (
          <Select id={id} name="kind" defaultValue="phone">
            <option value="phone">Phone</option>
            <option value="email">Email</option>
            <option value="domain">Website</option>
          </Select>
        )}
      </Field>
      <Field label="Phone, email or website" error={state && !state.ok ? state.message : undefined}>
        {({ id, describedBy, invalid }) => <Input id={id} name="value" required placeholder="+91 98110 12345" aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
      </Field>
      <Field label="Reason">
        {({ id }) => (
          <Select id={id} name="reason" defaultValue="opt_out">
            {SUPPRESSION_REASONS.map((r) => (
              <option key={r} value={r}>
                {SUPPRESSION_REASON_LABEL[r]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <SubmitButton>Add</SubmitButton>
    </form>
  )
}

export function RemoveSuppressionButton({ id, label }: { id: string; label: string }) {
  const [open, setOpen] = useState(false)
  const [pending, start] = useTransition()
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        Remove
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Remove from do-not-contact?" description={`${label} can be offered again by the engine and contacted from the app.`}>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Keep it
            </Button>
            <Button
              variant="danger"
              loading={pending}
              onClick={() =>
                start(async () => {
                  const r = await removeSuppression(id)
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
