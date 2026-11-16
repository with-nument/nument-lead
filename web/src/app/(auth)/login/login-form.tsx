'use client'

import { startTransition, useActionState, useId, useRef, useState, useSyncExternalStore } from 'react'
import { spinCoins } from '@/components/auth/spin'
import { cx } from '@/components/ui2/cx'
import { login, type AuthFormState } from '../actions'
import { AuthButton, AuthMessage, AuthNote, signinFields } from '../auth-ui'
import { buttonLabel, decide, type Step } from './steps'

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

// The password row slides open under the email (the mock's timing).
const reveal = '[transition:max-height_.45s_cubic-bezier(.2,0,0,1),opacity_.35s,translate_.45s_cubic-bezier(.2,0,0,1)]'

export function LoginForm() {
  const [state, dispatch, pending] = useActionState<AuthFormState, FormData>(login, undefined)
  const { next, linkError } = useQuery()
  const id = useId()
  const [step, setStep] = useState<Step>('email')
  // Once open, the row stops clipping so the password field's focus ring shows in full.
  const [opened, setOpened] = useState(false)
  const [show, setShow] = useState(false)
  const [local, setLocal] = useState<{ field: 'email' | 'password'; message: string } | null>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)

  const message = local?.message ?? state?.message ?? (linkError ? 'That link has expired. Ask for a new one.' : '')
  const errorId = `${id}-error`
  const invalid = (field: 'email' | 'password') => (local ? local.field === field : Boolean(state?.message)) || undefined

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (pending) return
    const data = new FormData(e.currentTarget)
    const d = decide(step, String(data.get('email') ?? ''), String(data.get('password') ?? ''))
    if (d.kind === 'error') {
      setLocal({ field: d.field, message: d.message })
      ;(d.field === 'email' ? emailRef : passwordRef).current?.focus()
      return
    }
    setLocal(null)
    spinCoins()
    if (d.kind === 'next') {
      setStep('password')
      setTimeout(() => passwordRef.current?.focus(), 250)
      return
    }
    startTransition(() => dispatch(data))
  }

  return (
    <form onSubmit={onSubmit} noValidate autoComplete="on">
      <input type="hidden" name="next" value={next} />
      <div className={signinFields}>
        <div>
          <label htmlFor={`${id}-email`} className="sr-only">
            Email
          </label>
          <input
            ref={emailRef}
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
            aria-invalid={invalid('email')}
            aria-describedby={message ? errorId : undefined}
          />
        </div>
        <div
          inert={step === 'email'}
          onTransitionEnd={(e) => {
            if (e.target === e.currentTarget && e.propertyName === 'max-height' && step === 'password') setOpened(true)
          }}
          className={cx(
            reveal,
            step === 'password' ? 'max-h-[70px] translate-y-0 opacity-100' : 'max-h-0 -translate-y-1.5 opacity-0',
            opened ? 'overflow-visible' : 'overflow-hidden',
          )}
        >
          <div className="relative">
            <label htmlFor={`${id}-password`} className="sr-only">
              Password
            </label>
            <input
              ref={passwordRef}
              id={`${id}-password`}
              name="password"
              type={show ? 'text' : 'password'}
              autoComplete="current-password"
              required
              placeholder="Password"
              className={'signin-field pr-[72px]'}
              aria-invalid={invalid('password')}
              aria-describedby={message ? errorId : undefined}
            />
            <button
              type="button"
              onClick={() => setShow((s) => !s)}
              aria-label={show ? 'Hide password' : 'Show password'}
              aria-controls={`${id}-password`}
              className="absolute top-1/2 right-4 -translate-y-1/2 cursor-pointer rounded-[4px] text-[14px] text-signin-ink"
            >
              {show ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
      </div>
      <AuthMessage id={errorId}>{message}</AuthMessage>
      <AuthButton pending={pending} pendingLabel="Signing in…">
        {buttonLabel(step)}
      </AuthButton>
      <AuthNote>
        {step === 'email' ? (
          'Access is by invite only. There is no public sign-up.'
        ) : (
          <a href="/reset-password" className="signin-link">
            Forgot password?
          </a>
        )}
      </AuthNote>
    </form>
  )
}
