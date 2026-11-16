'use client'

import { useActionState, useId } from 'react'
import { requestReset, type AuthFormState } from '../actions'
import { AuthMessage, AuthNote, AuthSubmit, signinFields } from '../auth-ui'

export function ResetRequestForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(requestReset, undefined)
  const id = useId()
  const error = state?.fieldErrors?.email?.[0]
  return (
    <form action={action} noValidate>
      <div className={signinFields}>
        <div>
          <label htmlFor={`${id}-email`} className="sr-only">
            Email
          </label>
          <input
            id={`${id}-email`}
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            required
            placeholder="Email"
            className="signin-field"
            aria-invalid={error ? true : undefined}
            aria-describedby={`${id}-message`}
          />
        </div>
      </div>
      {state?.ok ? (
        <AuthMessage id={`${id}-message`} tone="info">
          {state.message} No email after a few minutes? Ask your admin to reset your password from Settings.
        </AuthMessage>
      ) : (
        <AuthMessage id={`${id}-message`}>{error}</AuthMessage>
      )}
      <AuthSubmit pendingLabel="Sending…">Send reset link</AuthSubmit>
      <AuthNote>
        <a href="/login" className="signin-link">
          Back to sign in
        </a>
      </AuthNote>
    </form>
  )
}
