import 'server-only'
import { cache } from 'react'
import { redirect } from 'next/navigation'
import { connection } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { mustChangePassword } from '@/lib/password-flag'
import { isRole, type Role } from '@/lib/roles'
import { completedAtOf } from '@/lib/tour'
import { timed } from '@/lib/perf'

export type SessionUser = {
  id: string
  email: string
  name: string
  role: Role
  mustChangePassword: boolean
  /** When the product tour was finished or skipped (user_metadata, so only ever used to hide the tour). */
  tourCompletedAt: string | null
}

/**
 * The verified JWT claims for this request, or null. Checked locally against the project's signing keys
 * (no Auth server call), once per request. Good enough to scope a query to the user (`sub`) and start it
 * early, because every query still runs with the user's own token under Row Level Security. Access
 * decisions use `getSessionUser()`, which also asks the Auth server.
 */
export const getClaims = cache(async () => {
  // Per-request work: token checks read the clock, so keep it out of any prerender or prefetch.
  await connection()
  const supabase = await createClient()
  const { data } = await timed('server', 'getClaims', () => supabase.auth.getClaims())
  return data?.claims ?? null
})

/**
 * The signed-in user with their role, or null. Verified with the Auth server (getUser), so a
 * disabled user loses access at once. Cached per request, so pages and layouts can call it freely:
 * one getClaims, one getUser and one profile read per request, however many components ask.
 */
export const getSessionUser = cache(async (): Promise<SessionUser | null> => {
  const claims = await getClaims()
  const sub = claims?.sub
  if (!sub) return null
  const supabase = await createClient()

  const [userRes, profileRes] = await Promise.all([
    supabase.auth.getUser(),
    supabase.from('profiles').select('role, full_name').eq('user_id', sub).maybeSingle(),
  ])
  const user = userRes.data.user
  if (userRes.error || !user || user.id !== sub) return null
  const profile = profileRes.data
  if (!profile || !isRole(profile.role)) return null

  const email = user.email ?? ''
  return {
    id: user.id,
    email,
    name: profile.full_name?.trim() || email.split('@')[0] || 'User',
    role: profile.role,
    mustChangePassword: mustChangePassword(user.app_metadata),
    tourCompletedAt: completedAtOf(user.user_metadata),
  }
})

/** The user id from the verified token, for queries started before the full session check finishes. */
export async function claimedUserId(): Promise<string | null> {
  return (await getClaims())?.sub ?? null
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

/** Any signed-in user. Sends everyone else to the login page. */
export async function requireUser(): Promise<SessionUser> {
  const user = await getSessionUser()
  if (!user) redirect('/login')
  return user
}

/** A signed-in user with one of the given roles. Others go to Today. */
export async function requireRole(roles: readonly Role[]): Promise<SessionUser> {
  const user = await requireUser()
  if (!roles.includes(user.role)) redirect('/')
  return user
}
