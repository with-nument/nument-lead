import { describe, expect, it } from 'vitest'
import { flagUpdate, mustChangePassword } from '@/lib/password-flag'

describe('mustChangePassword', () => {
  it('only trusts a boolean true in app_metadata', () => {
    expect(mustChangePassword({ provider: 'email', must_change_password: true })).toBe(true)
    expect(mustChangePassword({ must_change_password: false })).toBe(false)
    expect(mustChangePassword({ must_change_password: 'true' })).toBe(false)
    expect(mustChangePassword({})).toBe(false)
    expect(mustChangePassword(undefined)).toBe(false)
    expect(mustChangePassword(null)).toBe(false)
  })
})

describe('flagUpdate', () => {
  it('merges into app_metadata and keeps the provider keys', () => {
    const u = flagUpdate({ provider: 'email', providers: ['email'] }, true)
    expect(u.app_metadata).toEqual({ provider: 'email', providers: ['email'], must_change_password: true })
  })

  it('removes the old user_metadata copy (null deletes the key)', () => {
    expect(flagUpdate(undefined, false)).toEqual({ app_metadata: { must_change_password: false }, user_metadata: { must_change_password: null } })
  })
})
