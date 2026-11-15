import 'server-only'
import { cache } from 'react'
import { redirect } from 'next/navigation'
import { connection } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { userFromClaims, userFromProfile, type SessionUser } from '@/lib/auth-claims'
import type { Role } from '@/lib/roles'
import { timed } from '@/lib/perf'

export type { SessionUser } from '@/lib/auth-claims'

/**
 * The verified JWT claims for this request, or null. Checked locally against the project's signing keys
 * (no Auth server call), once per request. Good enough to scope a query to the user (`sub`) and start it
 * early, because every query still runs with the user's own token under Row Level Security.
 */
export const getClaims = cache(async () => {
  // Per-request work: token checks read the clock, so keep it out of any prerender or prefetch.
  await connection()
  const supabase = await createClient()
  const { data } = await timed('server', 'getClaims', () => supabase.auth.getClaims())
  return data?.claims ?? null
})

/**
 * The signed-in user with their role, or null, from the verified token alone: no network call. The access
 * token hook (migration 0023) puts the role and name in the token; until it is switched on, or for a token
 * issued before it was, the profile is read instead (one database call). Cached per request, so pages and
 * layouts can call it freely.
 *
 * The role decides what the app shows. It never widens access: Row Level Security reads the profile for every
 * query, money comes only through the admin view, and the actions that matter (users, money, passwords) use
 * `requireRole(..., { verified: true })`, which asks the Auth server. A role change reaches the token at its
 * next refresh; a disabled user's sessions are ended at once (Settings > Users), so their token stops being
 * refreshed and they are signed out when it expires.
 */
export const getSessionUser = cache(async (): Promise<SessionUser | null> => {
  const claims = await getClaims()
  const sub = typeof claims?.sub === 'string' ? claims.sub : ''
  if (!sub) return null
  const fromToken = userFromClaims(claims)
  if (fromToken) return fromToken
  const supabase = await createClient()
  const { data: profile } = await supabase.from('profiles').select('role, full_name').eq('user_id', sub).maybeSingle()
  return userFromProfile(claims, profile)
})

/**
 * The signed-in user checked with the Auth server (getUser), with the role read from the profile now: a
 * disabled or deleted user, or a revoked session, gets null at once, and a role change counts at once. One Auth
 * call and one database call, so only for the actions that matter (user management, money, passwords).
 */
export const getVerifiedUser = cache(async (): Promise<SessionUser | null> => {
  const claims = await getClaims()
  const sub = typeof claims?.sub === 'string' ? claims.sub : ''
  if (!sub) return null
  const supabase = await createClient()
  const [userRes, profileRes] = await Promise.all([
    supabase.auth.getUser(),
    supabase.from('profiles').select('role, full_name').eq('user_id', sub).maybeSingle(),
  ])
  const user = userRes.data.user
  if (userRes.error || !user || user.id !== sub) return null
  return userFromProfile(
    { sub: user.id, email: user.email ?? '', app_metadata: user.app_metadata, user_metadata: user.user_metadata },
    profileRes.data,
  )
})

/** The user id from the verified token, for queries started before the full session check finishes. */
export async function claimedUserId(): Promise<string | null> {
  const sub = (await getClaims())?.sub
  return typeof sub === 'string' && sub ? sub : null
}

/**
 * Lets a page start its queries while the session check runs, instead of after it. The promise is
 * returned as is (await it as usual); a rejection is only marked handled, so a page that redirects
 * before awaiting it never leaves an unhandled rejection behind. Use it only for queries that run as
 * the signed-in user (Row Level Security applies), never for the service role.
 */
export function early<T>(promise: Promise<T>): Promise<T> {
  promise.catch(() => {})
  return promise
}

type CheckOptions = {
  /** Ask the Auth server and read the role from the profile now, instead of trusting the token (getVerifiedUser). */
  verified?: boolean
}

/** Any signed-in user. Sends everyone else to the login page. */
export async function requireUser(opts: CheckOptions = {}): Promise<SessionUser> {
  const user = opts.verified ? await getVerifiedUser() : await getSessionUser()
  if (!user) redirect('/login')
  return user
}

/** A signed-in user with one of the given roles. Others go to Today. */
export async function requireRole(roles: readonly Role[], opts: CheckOptions = {}): Promise<SessionUser> {
  const user = await requireUser(opts)
  if (!roles.includes(user.role)) redirect('/')
  return user
}
