'use client'

import Link from 'next/link'
import { useActionState, useId } from 'react'
import { useFormStatus } from 'react-dom'
import { useHydrated } from '@/lib/use-hydrated'
import { Spinner } from '@/components/ui/spinner'
import { updatePassword, type AuthFormState } from '../../actions'
import { AuthAlert, authInput, authPrimary } from '../../auth-ui'

function Submit() {
  const { pending } = useFormStatus()
  const hydrated = useHydrated()
  return (
    <button type="submit" className={authPrimary} disabled={pending || !hydrated} data-hydrating={hydrated ? undefined : true} aria-busy={pending || undefined}>
      {pending ? <Spinner label="Saving" /> : 'Save new password'}
    </button>
  )
}

export function NewPasswordForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(updatePassword, undefined)
  const id = useId()
  const pwError = state?.fieldErrors?.password?.[0]
  const confirmError = state?.fieldErrors?.confirm?.[0]
  return (
    <form action={action} className="flex flex-col gap-3" noValidate>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-pw`} className="text-sm font-medium text-tx-2">
          New password
        </label>
        <input
          id={`${id}-pw`}
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          className={authInput}
          aria-invalid={pwError ? true : undefined}
          aria-describedby={pwError ? `${id}-pw-error` : undefined}
        />
        {pwError ? (
          <p id={`${id}-pw-error`} className="text-xs text-bad">
            {pwError}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-confirm`} className="text-sm font-medium text-tx-2">
          Type it again
        </label>
        <input
          id={`${id}-confirm`}
          name="confirm"
          type="password"
          autoComplete="new-password"
          required
          className={authInput}
          aria-invalid={confirmError ? true : undefined}
          aria-describedby={confirmError ? `${id}-confirm-error` : undefined}
        />
        {confirmError ? (
          <p id={`${id}-confirm-error`} className="text-xs text-bad">
            {confirmError}
          </p>
        ) : null}
      </div>
      {state?.message && !state.fieldErrors ? <AuthAlert>{state.message}</AuthAlert> : null}
      <div className="mt-2">
        <Submit />
      </div>
      <p className="mt-4 text-center text-sm">
        <Link href="/reset-password" className="text-tx-3 underline-offset-2 hover:text-indigo-800 hover:underline">
          Need a new link?
        </Link>
      </p>
    </form>
  )
}
