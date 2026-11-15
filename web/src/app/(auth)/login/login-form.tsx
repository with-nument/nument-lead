'use client'

import { useActionState, useId, useState, useSyncExternalStore } from 'react'
import { FieldGroup, FieldRow, fieldInput } from '@/components/ui2/field-group'
import { login, type AuthFormState } from '../actions'
import { AuthAlert, AuthLink, AuthSubmit, EyeIcon } from '../auth-ui'

const noop = () => () => {}

/** The page is fully static; `next` and `error` are read from the address bar in the browser. */
function useQuery() {
  const search = useSyncExternalStore(
    noop,
    () => window.location.search,
    () => '',
  )
  const params = new URLSearchParams(search)
  return { next: params.get('next') ?? '', linkError: params.get('error') === 'link' }
}

export function LoginForm() {
  const [state, action] = useActionState<AuthFormState, FormData>(login, undefined)
  const { next, linkError } = useQuery()
  const [show, setShow] = useState(false)
  const id = useId()
  const invalid = state?.message ? true : undefined
  const describedBy = state?.message ? `${id}-error` : undefined
  return (
    <form action={action} className="flex flex-col" noValidate>
      <input type="hidden" name="next" value={next} />
      {linkError && !state?.message ? <AuthAlert className="mb-4">That link has expired. Ask for a new one.</AuthAlert> : null}
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
            aria-invalid={invalid}
            aria-describedby={describedBy}
          />
        </FieldRow>
        <FieldRow
          label="Password"
          htmlFor={`${id}-password`}
          trailing={
            <button
              type="button"
              onClick={() => setShow((s) => !s)}
              aria-label={show ? 'Hide password' : 'Show password'}
              aria-pressed={show}
              aria-controls={`${id}-password`}
              className="grid size-9 shrink-0 place-items-center rounded-full text-label-3 transition-colors hover:bg-fill-3 hover:text-label-1"
            >
              <EyeIcon off={show} />
            </button>
          }
        >
          <input
            id={`${id}-password`}
            name="password"
            type={show ? 'text' : 'password'}
            autoComplete="current-password"
            required
            placeholder="Required"
            className={fieldInput}
            aria-invalid={invalid}
            aria-describedby={describedBy}
          />
        </FieldRow>
      </FieldGroup>
      {state?.message ? (
        <AuthAlert id={`${id}-error`} className="mt-3">
          {state.message}
        </AuthAlert>
      ) : null}
      <div className="mt-6">
        <AuthSubmit pendingLabel="Signing in">Sign in</AuthSubmit>
      </div>
      <AuthLink href="/reset-password">Forgot password?</AuthLink>
      <p className="type-caption mt-7 text-center text-label-3">There is no public sign-up.</p>
    </form>
  )
}
