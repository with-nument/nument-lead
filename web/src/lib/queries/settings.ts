import 'server-only'
import { createAdminClient } from '@/lib/supabase/admin'
import { createClient } from '@/lib/supabase/server'
import { mustChangePassword } from '@/lib/password-flag'
import { isRole, type Role } from '@/lib/roles'

export type AppUser = {
  id: string
  email: string
  name: string
  role: Role | null
  lastSignInAt: string | null
  createdAt: string
  disabled: boolean
  mustChangePassword: boolean
}

/** Users and roles for /settings/users. Admin only: the page checks the role before calling. */
export async function getUsers(): Promise<AppUser[]> {
  const admin = createAdminClient()
  const [{ data: list, error }, { data: profiles, error: pError }] = await Promise.all([
    admin.auth.admin.listUsers({ page: 1, perPage: 200 }),
    admin.from('profiles').select('user_id, full_name, role'),
  ])
  if (error) throw error
  if (pError) throw pError
  const byId = new Map((profiles ?? []).map((p) => [p.user_id, p]))
  const now = Date.now()
  return (list?.users ?? [])
    .map((u) => {
      const p = byId.get(u.id)
      const bannedUntil = (u as { banned_until?: string | null }).banned_until
      return {
        id: u.id,
        email: u.email ?? '',
        name: p?.full_name?.trim() || (u.user_metadata?.full_name as string | undefined) || u.email?.split('@')[0] || 'User',
        role: isRole(p?.role) ? p.role : null,
        lastSignInAt: u.last_sign_in_at ?? null,
        createdAt: u.created_at,
        disabled: Boolean(bannedUntil && Date.parse(bannedUntil) > now),
        mustChangePassword: mustChangePassword(u.app_metadata),
      }
    })
    .sort((a, b) => a.name.localeCompare(b.name))
}

export async function getSuppression() {
  const sb = await createClient()
  const { data, error } = await sb
    .from('suppression')
    .select('id, phone_e164, email, web_domain, reason, added_by, added_at')
    .order('added_at', { ascending: false })
    .limit(500)
  if (error) throw error
  return data ?? []
}

/** Settings > Email recipients. Admin only: Row Level Security returns nothing to anyone else. */
export async function getRecipients() {
  const sb = await createClient()
  const { data, error } = await sb
    .from('notify_recipients')
    .select('id, email, name, morning, alerts, weekly, active, created_at')
    .order('created_at', { ascending: true })
    .limit(200)
  if (error) throw error
  return data ?? []
}
