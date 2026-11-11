'use client'

import { useActionState, useRef } from 'react'
import { toast } from 'sonner'
import { addInboxPost } from '@/app/(app)/inbox/actions'
import { Field } from '@/components/ui/field'
import { Input, Select, Textarea } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import type { ActionResult } from '@/lib/action-result'

export function InboxForm({ segments }: { segments: { id: string; label: string }[] }) {
  const formRef = useRef<HTMLFormElement>(null)
  const [state, action] = useActionState<ActionResult | undefined, FormData>(async (prev, fd) => {
    const r = await addInboxPost(prev, fd)
    if (r.ok) {
      toast(r.message ?? 'Added')
      formRef.current?.reset()
    }
    return r
  }, undefined)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form ref={formRef} action={action} className="grid gap-3">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
        <Field label="Link to the post (optional)" error={errors?.url}>
          {({ id, describedBy, invalid }) => <Input id={id} name="url" type="url" placeholder="https://" aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
        </Field>
        <Field label="Segment (optional)">
          {({ id }) => (
            <Select id={id} name="segmentId" defaultValue="">
              <option value="">Let the engine decide</option>
              {segments.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <Field label="Post text" hint="Copy the words of the post by hand. Names of private people are not needed." error={errors?.text}>
        {({ id, describedBy, invalid }) => <Textarea id={id} name="text" rows={4} required aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
      </Field>
      {state && !state.ok && !state.fieldErrors ? <p className="text-sm text-bad">{state.message}</p> : null}
      <div>
        <SubmitButton>Add to inbox</SubmitButton>
      </div>
    </form>
  )
}
