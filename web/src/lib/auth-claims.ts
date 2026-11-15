// Who the signed-in user is, read from the access token's claims. Pure (no server or network access), so it
// can be unit tested; lib/auth.ts reads the claims and decides when to ask the database or the Auth server.
//
// The custom access token hook (supabase/migrations/0023_auth_claims.sql) adds `user_role` and `full_name`
// from public.profiles to every token. Until the hook is switched on, or for a token issued before it was,
// the claims have no role and the caller falls back to reading the profile.
import { mustChangePassword } from '@/lib/password-flag'
import { isRole, type Role } from '@/lib/roles'
import { completedAtOf } from '@/lib/tour'

export type SessionUser = {
  id: string
  email: string
  name: string
  role: Role
  mustChangePassword: boolean
  /** When the product tour was finished or skipped (user_metadata, so only ever used to hide the tour). */
  tourCompletedAt: string | null
}

/** The JWT claims this module reads. Anything else in the token is ignored. */
export type TokenClaims = {
  sub?: unknown
  email?: unknown
  app_metadata?: unknown
  user_metadata?: unknown
  user_role?: unknown
  full_name?: unknown
}

export type ProfileRow = { role: string | null; full_name: string | null }

const text = (v: unknown) => (typeof v === 'string' ? v : '')

/** The name to show: the profile name, else the part of the email before the @, else "User". */
export const displayName = (fullName: string | null | undefined, email: string) => fullName?.trim() || email.split('@')[0] || 'User'

/**
 * The user as the token describes them, when the token carries a valid role (the hook is on). Null when it
 * does not, so the caller reads the profile instead. The role here only decides what the app shows and which
 * pages open; Row Level Security reads the profile for every query, so a stale role never widens access.
 */
export function userFromClaims(claims: TokenClaims | null | undefined): SessionUser | null {
  const id = text(claims?.sub)
  if (!claims || !id || !isRole(claims.user_role)) return null
  const email = text(claims.email)
  return {
    id,
    email,
    name: displayName(typeof claims.full_name === 'string' ? claims.full_name : null, email),
    role: claims.user_role,
    mustChangePassword: mustChangePassword(claims.app_metadata),
    tourCompletedAt: completedAtOf(claims.user_metadata),
  }
}

/** The user from the token's identity and their profile row (the fallback path). Null without a valid role. */
export function userFromProfile(claims: TokenClaims | null | undefined, profile: ProfileRow | null | undefined): SessionUser | null {
  const id = text(claims?.sub)
  if (!claims || !id || !profile || !isRole(profile.role)) return null
  const email = text(claims.email)
  return {
    id,
    email,
    name: displayName(profile.full_name, email),
    role: profile.role,
    mustChangePassword: mustChangePassword(claims.app_metadata),
    tourCompletedAt: completedAtOf(claims.user_metadata),
  }
}
