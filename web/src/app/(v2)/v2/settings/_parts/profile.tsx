'use client'

import { useState } from 'react'
import { changePassword, signOutOtherSessions, updateProfile } from '@/app/(app)/settings/actions'
import { Field, FormError, inputClass, Submit } from '@/app/(v2)/v2/_parts/form'
import { RowButton } from '@/app/(v2)/v2/_parts/row-button'
import { useFormAction, useRun } from '@/app/(v2)/v2/_parts/run'
import { Panel, Row } from '@/app/(v2)/v2/_parts/section'
import { Button } from '@/components/ui2/button'
import { Sheet, SheetContent } from '@/components/ui2/sheet'

type Sheets = 'name' | 'password' | null

/** Settings > Profile: name, email, role, password, time zone and the other sessions. */
export function ProfilePanel({ name, email, roleLabel, roleHint }: { name: string; email: string; roleLabel: string; roleHint: string }) {
  const [open, setOpen] = useState<Sheets>(null)
  const [pending, run] = useRun()
  return (
    <>
      <Panel>
        <RowButton label="Name" onClick={() => setOpen('name')}>
          {name}
        </RowButton>
        <Row label="Email">
          <span className="block truncate">{email}</span>
        </Row>
        <Row label="Role">
          <span className="block">{roleLabel}</span>
          <span className="type-caption block text-label-3">{roleHint}</span>
        </Row>
        <RowButton label="Password" onClick={() => setOpen('password')}>
          Change password
        </RowButton>
        <Row label="Time zone">India (IST)</Row>
        <Row
          label="Sessions"
          trailing={
            <Button size="small" disabled={pending} onClick={() => run(() => signOutOtherSessions())}>
              Sign out others
            </Button>
          }
        >
          <span className="hidden truncate text-label-3 sm:block">Other phones and computers</span>
        </Row>
      </Panel>
      <Sheet open={open === 'name'} onOpenChange={(o) => setOpen(o ? 'name' : null)}>
        <SheetContent title="Your name" description="Shown to your team on leads and in the timeline.">
          <NameForm name={name} onDone={() => setOpen(null)} />
        </SheetContent>
      </Sheet>
      <Sheet open={open === 'password'} onOpenChange={(o) => setOpen(o ? 'password' : null)}>
        <SheetContent title="Change password">
          <PasswordForm onDone={() => setOpen(null)} />
        </SheetContent>
      </Sheet>
    </>
  )
}

function NameForm({ name, onDone }: { name: string; onDone: () => void }) {
  const [state, action, pending] = useFormAction(updateProfile, onDone)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="flex flex-col gap-4" noValidate>
      <Field label="Full name" error={errors?.fullName}>
        {({ id, describedBy, invalid }) => (
          <input id={id} name="fullName" defaultValue={name} autoComplete="name" required className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
      <div>
        <Submit pending={pending}>Save name</Submit>
      </div>
    </form>
  )
}

/** The password form. `forced`: the first sign in with a temporary password; the app opens after it. */
export function PasswordForm({ forced, onDone }: { forced?: boolean; onDone?: () => void }) {
  const [state, action, pending] = useFormAction(changePassword, () => onDone?.())
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="flex flex-col gap-4" noValidate>
      {forced ? <input type="hidden" name="forced" value="1" /> : null}
      <Field label="New password" hint="At least 12 characters, with upper and lower case letters, a number and a symbol." error={errors?.password}>
        {({ id, describedBy, invalid }) => (
          <input id={id} name="password" type="password" autoComplete="new-password" required minLength={12} className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Type it again" error={errors?.confirm}>
        {({ id, describedBy, invalid }) => (
          <input id={id} name="confirm" type="password" autoComplete="new-password" required className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
      <div>
        <Submit pending={pending}>{forced ? 'Set password and continue' : 'Change password'}</Submit>
      </div>
    </form>
  )
}
