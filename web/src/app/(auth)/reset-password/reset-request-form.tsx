'use client'

import { useActionState, useId } from 'react'
import { FieldGroup, FieldRow, fieldInput } from '@/components/ui2/field-group'
import { requestReset, type AuthFormState } from '../actions'
import { AuthAlert, AuthLink, AuthSubmit } from '../auth-ui'

export function ResetRequestForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(requestReset, undefined)
  const id = useId()
  const error = state?.fieldErrors?.email?.[0]
  return (
    <form action={action} className="flex flex-col" noValidate>
      <FieldGroup>
        <FieldRow label="Email" htmlFor={`${id}-email`}>
          <input
            id={`${id}-email`}
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            required
            placeholder="name@nument.in"
            className={fieldInput}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-error` : undefined}
          />
        </FieldRow>
      </FieldGroup>
      {error ? (
        <AuthAlert id={`${id}-error`} className="mt-3">
          {error}
        </AuthAlert>
      ) : null}
      {state?.ok ? (
        <AuthAlert tone="info" className="mt-3">
          {state.message} No email after a few minutes? Ask your admin to reset your password from Settings.
        </AuthAlert>
      ) : null}
      <div className="mt-6">
        <AuthSubmit pendingLabel="Sending">Send reset link</AuthSubmit>
      </div>
      <AuthLink href="/login">Back to sign in</AuthLink>
    </form>
  )
}
