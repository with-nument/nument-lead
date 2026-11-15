'use client'

import { useActionState, useId } from 'react'
import { FieldGroup, FieldRow, fieldInput } from '@/components/ui2/field-group'
import { updatePassword, type AuthFormState } from '../../actions'
import { AuthAlert, AuthLink, AuthSubmit } from '../../auth-ui'

export function NewPasswordForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(updatePassword, undefined)
  const id = useId()
  const pwError = state?.fieldErrors?.password?.[0]
  const confirmError = state?.fieldErrors?.confirm?.[0]
  return (
    <form action={action} className="flex flex-col" noValidate>
      <FieldGroup>
        <FieldRow label="New password" htmlFor={`${id}-pw`}>
          <input
            id={`${id}-pw`}
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            placeholder="12 or more characters"
            className={fieldInput}
            aria-invalid={pwError ? true : undefined}
            aria-describedby={pwError ? `${id}-pw-error` : undefined}
          />
        </FieldRow>
        <FieldRow label="Type it again" htmlFor={`${id}-confirm`}>
          <input
            id={`${id}-confirm`}
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            placeholder="Same password"
            className={fieldInput}
            aria-invalid={confirmError ? true : undefined}
            aria-describedby={confirmError ? `${id}-confirm-error` : undefined}
          />
        </FieldRow>
      </FieldGroup>
      {pwError ? (
        <AuthAlert id={`${id}-pw-error`} className="mt-3">
          {pwError}
        </AuthAlert>
      ) : null}
      {confirmError ? (
        <AuthAlert id={`${id}-confirm-error`} className="mt-3">
          {confirmError}
        </AuthAlert>
      ) : null}
      {state?.message && !state.fieldErrors ? <AuthAlert className="mt-3">{state.message}</AuthAlert> : null}
      <div className="mt-6">
        <AuthSubmit pendingLabel="Saving">Save new password</AuthSubmit>
      </div>
      <AuthLink href="/reset-password">Need a new link?</AuthLink>
    </form>
  )
}
