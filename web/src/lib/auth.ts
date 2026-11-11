import 'server-only'
import { cache } from 'react'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { isRole, type Role } from '@/lib/roles'

export type SessionUser = {
  id: string
  email: string
  name: string
  role: Role
  mustChangePassword: boolean
}

/**
 * The signed-in user with their role, or null. Verified with the Auth server (getUser), so a
 * disabled user loses access at once. Cached per request, so pages and layouts can call it freely.
 */
export const getSessionUser = cache(async (): Promise<SessionUser | null> => {
  const supabase = await createClient()
  const { data: claimsData } = await supabase.auth.getClaims()
  const sub = claimsData?.claims?.sub
  if (!sub) return null

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
    mustChangePassword: user.user_metadata?.must_change_password === true,
  }
})

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
