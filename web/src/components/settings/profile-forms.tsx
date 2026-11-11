'use client'

import { useActionState, useTransition } from 'react'
import { LogOut } from 'lucide-react'
import { toast } from 'sonner'
import { logout } from '@/app/(auth)/actions'
import { changePassword, signOutOtherSessions, updateProfile } from '@/app/(app)/settings/actions'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import type { ActionResult } from '@/lib/action-result'
import { useHydrated } from '@/lib/use-hydrated'

function withToast(fn: (prev: unknown, fd: FormData) => Promise<ActionResult>) {
  return async (prev: ActionResult | undefined, fd: FormData) => {
    const r = await fn(prev, fd)
    if (r.ok) toast(r.message ?? 'Saved')
    return r
  }
}

export function NameForm({ name, email }: { name: string; email: string }) {
  const [state, action] = useActionState(withToast(updateProfile), undefined)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-2">
      <Field label="Full name" error={errors?.fullName}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="fullName" defaultValue={name} autoComplete="name" required aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Email" hint="Ask an admin to change it.">
        {({ id, describedBy }) => <Input id={id} value={email} readOnly disabled aria-describedby={describedBy} />}
      </Field>
      <div className="sm:col-span-2">
        <SubmitButton>Save name</SubmitButton>
      </div>
    </form>
  )
}

export function PasswordForm({ forced }: { forced: boolean }) {
  const [state, action] = useActionState(withToast(changePassword), undefined)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-2">
      {forced ? <input type="hidden" name="forced" value="1" /> : null}
      <Field label="New password" hint="At least 12 characters, with upper and lower case letters, a number and a symbol." error={errors?.password}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="password" type="password" autoComplete="new-password" required minLength={12} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Type it again" error={errors?.confirm}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="confirm" type="password" autoComplete="new-password" required aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      {state && !state.ok && !state.fieldErrors ? <p className="text-sm text-bad sm:col-span-2">{state.message}</p> : null}
      <div className="sm:col-span-2">
        <SubmitButton>{forced ? 'Set my password' : 'Change password'}</SubmitButton>
      </div>
    </form>
  )
}

export function SessionButtons() {
  const [pending, start] = useTransition()
  const hydrated = useHydrated()
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        variant="secondary"
        loading={pending}
        onClick={() =>
          start(async () => {
            const r = await signOutOtherSessions()
            if (r.ok) toast(r.message ?? 'Done')
            else toast.error(r.message)
          })
        }
      >
        Sign out other devices
      </Button>
      <form action={logout}>
        <Button type="submit" variant="ghost" disabled={!hydrated} data-hydrating={hydrated ? undefined : true}>
          <LogOut aria-hidden />
          Log out
        </Button>
      </form>
    </div>
  )
}
