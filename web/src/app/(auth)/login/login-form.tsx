'use client'

import Link from 'next/link'
import { useActionState, useId } from 'react'
import { useFormStatus } from 'react-dom'
import { Spinner } from '@/components/ui/spinner'
import { login, type AuthFormState } from '../actions'
import { AuthAlert, authInput, authPrimary } from '../auth-ui'

function Submit() {
  const { pending } = useFormStatus()
  return (
    <button type="submit" className={authPrimary} disabled={pending} aria-busy={pending || undefined}>
      {pending ? <Spinner label="Signing in" /> : 'Sign in'}
    </button>
  )
}

export function LoginForm({ next, linkError }: { next: string; linkError: boolean }) {
  const [state, action] = useActionState<AuthFormState, FormData>(login, undefined)
  const id = useId()
  return (
    <form action={action} className="flex flex-col gap-3" noValidate>
      <input type="hidden" name="next" value={next} />
      {linkError && !state?.message ? <AuthAlert>That link has expired. Ask for a new one.</AuthAlert> : null}
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
          placeholder="name@nument.in"
          className={authInput}
          aria-invalid={state?.message ? true : undefined}
          aria-describedby={state?.message ? `${id}-error` : undefined}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between">
          <label htmlFor={`${id}-password`} className="text-sm font-medium text-tx-2">
            Password
          </label>
          <Link href="/reset-password" className="text-sm text-tx-3 underline-offset-2 hover:text-indigo-800 hover:underline">
            Forgot password?
          </Link>
        </div>
        <input
          id={`${id}-password`}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={authInput}
          aria-invalid={state?.message ? true : undefined}
          aria-describedby={state?.message ? `${id}-error` : undefined}
        />
      </div>
      {state?.message ? (
        <div id={`${id}-error`}>
          <AuthAlert>{state.message}</AuthAlert>
        </div>
      ) : null}
      <div className="mt-2">
        <Submit />
      </div>
      <p className="mt-4 text-center text-sm text-tx-3">New accounts are created by an admin. There is no public sign-up.</p>
    </form>
  )
}
