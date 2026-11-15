import { describe, expect, it } from 'vitest'
import { displayName, userFromClaims, userFromProfile } from '@/lib/auth-claims'

const ID = '00000000-0000-4000-8000-0000000000c1'
// What Supabase puts in an access token, plus the two claims the hook (migration 0023) adds.
const token = {
  sub: ID,
  role: 'authenticated',
  email: 'asha@example.com',
  app_metadata: { provider: 'email' },
  user_metadata: { full_name: 'Signup name' },
  user_role: 'caller',
  full_name: 'Asha Rao',
}

describe('userFromClaims (the hook is on)', () => {
  it('reads the role and name from the token', () => {
    expect(userFromClaims(token)).toEqual({
      id: ID,
      email: 'asha@example.com',
      name: 'Asha Rao',
      role: 'caller',
      mustChangePassword: false,
      tourCompletedAt: null,
    })
  })

  it('carries the temporary-password flag from app_metadata only', () => {
    expect(userFromClaims({ ...token, app_metadata: { must_change_password: true } })?.mustChangePassword).toBe(true)
    expect(userFromClaims({ ...token, user_metadata: { must_change_password: true } })?.mustChangePassword).toBe(false)
  })

  it('reads when the tour was finished', () => {
    const at = '2026-11-15T10:00:00.000Z'
    expect(userFromClaims({ ...token, user_metadata: { tour_completed_at: at } })?.tourCompletedAt).toBe(at)
    expect(userFromClaims({ ...token, user_metadata: { tour_completed_at: 'soon' } })?.tourCompletedAt).toBeNull()
  })

  it('falls back to the email for a missing or blank name', () => {
    expect(userFromClaims({ ...token, full_name: null })?.name).toBe('asha')
    expect(userFromClaims({ ...token, full_name: '   ' })?.name).toBe('asha')
    expect(userFromClaims({ ...token, full_name: undefined, email: '' })?.name).toBe('User')
  })

  it('returns null without a valid role, so the profile is read instead', () => {
    expect(userFromClaims({ ...token, user_role: undefined })).toBeNull() // the hook is off
    expect(userFromClaims({ ...token, user_role: null })).toBeNull()
    expect(userFromClaims({ ...token, user_role: 'owner' })).toBeNull() // not an app role
    expect(userFromClaims({ ...token, user_role: 'authenticated' })).toBeNull()
    expect(userFromClaims({ ...token, sub: '' })).toBeNull()
    expect(userFromClaims({ ...token, sub: 42 })).toBeNull()
    expect(userFromClaims(null)).toBeNull()
  })

  it('never mistakes the Postgres role claim for the app role', () => {
    const { user_role: _drop, ...plain } = token
    void _drop
    expect(userFromClaims({ ...plain, role: 'admin' })).toBeNull()
  })
})

describe('userFromProfile (the hook is off, or a verified check)', () => {
  it('takes the role and name from the profile and the rest from the token', () => {
    expect(userFromProfile({ ...token, user_role: 'viewer' }, { role: 'admin', full_name: ' Dev ' })).toEqual({
      id: ID,
      email: 'asha@example.com',
      name: 'Dev',
      role: 'admin',
      mustChangePassword: false,
      tourCompletedAt: null,
    })
  })

  it('returns null without a profile or with an unknown role', () => {
    expect(userFromProfile(token, null)).toBeNull()
    expect(userFromProfile(token, { role: 'superuser', full_name: 'X' })).toBeNull()
    expect(userFromProfile(token, { role: null, full_name: 'X' })).toBeNull()
    expect(userFromProfile({ email: 'a@b.c' }, { role: 'admin', full_name: 'X' })).toBeNull()
  })
})

describe('displayName', () => {
  it('prefers the name, then the email before the @', () => {
    expect(displayName('  Ravi  ', 'r@x.in')).toBe('Ravi')
    expect(displayName(null, 'ravi.k@x.in')).toBe('ravi.k')
    expect(displayName('', '')).toBe('User')
  })
})
