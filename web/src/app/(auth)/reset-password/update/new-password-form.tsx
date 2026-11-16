'use client'

import { useActionState, useId } from 'react'
import { updatePassword, type AuthFormState } from '../../actions'
import { AuthMessage, AuthNote, AuthSubmit, signinFields } from '../../auth-ui'

function FieldError({ id, children }: { id: string; children?: string }) {
  return children ? (
    <p id={id} className="mx-0.5 mt-1.5 text-[14px] leading-5 text-signin-ink">
      {children}
    </p>
  ) : null
}

export function NewPasswordForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(updatePassword, undefined)
  const id = useId()
  const pwError = state?.fieldErrors?.password?.[0]
  const confirmError = state?.fieldErrors?.confirm?.[0]
  return (
    <form action={action} noValidate>
      <div className={signinFields}>
        <div>
          <label htmlFor={`${id}-pw`} className="sr-only">
            New password
          </label>
          <input
            id={`${id}-pw`}
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            placeholder="New password"
            className="signin-field"
            aria-invalid={pwError ? true : undefined}
            aria-describedby={pwError ? `${id}-pw-error` : undefined}
          />
          <FieldError id={`${id}-pw-error`}>{pwError}</FieldError>
        </div>
        <div>
          <label htmlFor={`${id}-confirm`} className="sr-only">
            Type it again
          </label>
          <input
            id={`${id}-confirm`}
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            placeholder="Type it again"
            className="signin-field"
            aria-invalid={confirmError ? true : undefined}
            aria-describedby={confirmError ? `${id}-confirm-error` : undefined}
          />
          <FieldError id={`${id}-confirm-error`}>{confirmError}</FieldError>
        </div>
      </div>
      <AuthMessage>{state?.message && !state.fieldErrors ? state.message : null}</AuthMessage>
      <AuthSubmit pendingLabel="Saving…">Save new password</AuthSubmit>
      <AuthNote>
        <a href="/reset-password" className="signin-link">
          Need a new link?
        </a>
      </AuthNote>
    </form>
  )
}
