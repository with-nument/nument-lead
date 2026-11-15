'use client'

import Link from 'next/link'
import { useActionState, useId } from 'react'
import { useFormStatus } from 'react-dom'
import { useHydrated } from '@/lib/use-hydrated'
import { Spinner } from '@/components/ui/spinner'
import { requestReset, type AuthFormState } from '../actions'
import { AuthAlert, authInput, authPrimary } from '../auth-ui'

function Submit() {
  const { pending } = useFormStatus()
  const hydrated = useHydrated()
  return (
    <button type="submit" className={authPrimary} disabled={pending || !hydrated} data-hydrating={hydrated ? undefined : true} aria-busy={pending || undefined}>
      {pending ? <Spinner label="Sending" /> : 'Send reset link'}
    </button>
  )
}

export function ResetRequestForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(requestReset, undefined)
  const id = useId()
  const error = state?.fieldErrors?.email?.[0]
  return (
    <form action={action} className="flex flex-col gap-3" noValidate>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-email`} className="text-sm font-medium text-tx-2">
          Email
        </label>
        <input
          id={`${id}-email`}
          name="email"
          type="email"
          autoComplete="username"
          inputMode="email"
          required
          className={authInput}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
        />
        {error ? (
          <p id={`${id}-error`} className="text-xs text-bad">
            {error}
          </p>
        ) : null}
      </div>
      {state?.ok ? (
        <AuthAlert tone="info">
          {state.message} No email after a few minutes? Ask your admin to reset your password from Settings.
        </AuthAlert>
      ) : null}
      <div className="mt-2">
        <Submit />
      </div>
      <p className="mt-4 text-center text-sm">
        <Link href="/login" className="text-tx-3 underline-offset-2 hover:text-indigo-800 hover:underline">
          Back to sign in
        </Link>
      </p>
    </form>
  )
}
