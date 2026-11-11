import 'server-only'
import { createAdminClient } from '@/lib/supabase/admin'
import { flagUpdate } from '@/lib/password-flag'

/**
 * Sets or clears a user's temporary-password flag in app_metadata with the service role.
 * Server-only on purpose: it must never be reachable as a Server Action, or a user could clear
 * their own flag without changing the password. Callers check the session first.
 */
export async function setPasswordFlag(userId: string, value: boolean) {
  const admin = createAdminClient()
  const { data, error: readError } = await admin.auth.admin.getUserById(userId)
  if (readError || !data.user) throw new Error('User not found for the password flag update.')
  const { error } = await admin.auth.admin.updateUserById(userId, flagUpdate(data.user.app_metadata, value))
  if (error) throw new Error(`Password flag update failed (${error.status ?? 'unknown'}).`)
}
