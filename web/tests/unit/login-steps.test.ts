import { describe, expect, it } from 'vitest'
import { buttonLabel, decide } from '@/app/(auth)/login/steps'

describe('sign-in steps', () => {
  it('asks for a real-looking email before showing the password', () => {
    expect(decide('email', '', '')).toEqual({ kind: 'error', field: 'email', message: 'Enter the email your admin gave you.' })
    expect(decide('email', 'name@nument', '')).toMatchObject({ kind: 'error', field: 'email' })
    expect(decide('email', 'name @nument.in', '')).toMatchObject({ kind: 'error', field: 'email' })
    expect(decide('email', ' name@nument.in ', '')).toEqual({ kind: 'next' })
  })

  it('never submits from the email step, even with a password already filled in', () => {
    expect(decide('email', 'name@nument.in', 'secret')).toEqual({ kind: 'next' })
  })

  it('needs a password, then submits once', () => {
    expect(decide('password', 'name@nument.in', '')).toEqual({ kind: 'error', field: 'password', message: 'Enter your password.' })
    expect(decide('password', 'name@nument.in', 'secret')).toEqual({ kind: 'submit' })
  })

  it('checks the email again on the password step (it can still be edited)', () => {
    expect(decide('password', 'oops', 'secret')).toMatchObject({ kind: 'error', field: 'email' })
  })

  it('labels the button for each step', () => {
    expect(buttonLabel('email')).toBe('Continue with email')
    expect(buttonLabel('password')).toBe('Sign in')
  })
})
