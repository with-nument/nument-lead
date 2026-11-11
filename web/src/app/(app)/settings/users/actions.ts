'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createAdminClient } from '@/lib/supabase/admin'
import { fail, fieldErrorsOf, ok, type ActionResult } from '@/lib/action-result'
import { generateTempPassword } from '@/lib/password'
import { flagUpdate } from '@/lib/password-flag'
import { ROLES } from '@/lib/roles'

// User management (plan 15.3.4). Public sign-up is off: only an admin creates people, and every
// new or reset account must change its temporary password on first sign in.

const NewUser = z.object({
  email: z.email('Enter a valid email.').max(254),
  fullName: z.string().trim().min(2, 'Use at least 2 characters.').max(80, 'Use at most 80 characters.'),
  role: z.enum(ROLES),
})

export type CreatedUser = { email: string; tempPassword: string }

export async function createUser(_: unknown, formData: FormData): Promise<ActionResult<CreatedUser>> {
  await requireRole(['admin'])
  const parsed = NewUser.safeParse({
    email: String(formData.get('email') ?? '').trim().toLowerCase(),
    fullName: formData.get('fullName'),
    role: formData.get('role'),
  })
  if (!parsed.success) return fail('Check the highlighted fields.', fieldErrorsOf(parsed.error))
  const { email, fullName, role } = parsed.data
  const admin = createAdminClient()
  const tempPassword = generateTempPassword()
  const { data, error } = await admin.auth.admin.createUser({
    email,
    password: tempPassword,
    email_confirm: true,
    user_metadata: { full_name: fullName },
    // app_metadata, not user_metadata: users cannot clear it themselves (see lib/password-flag.ts).
    app_metadata: { must_change_password: true },
  })
  if (error || !data.user) {
    if (error?.code === 'email_exists' || error?.status === 422) return fail('An account with this email already exists.', { email: ['Already has an account.'] })
    console.error('createUser failed', error?.status, error?.code)
    return fail('Could not create the user. Try again.')
  }
  // The database trigger makes a viewer profile; set the chosen role and name with the service role.
  const { error: profileError } = await admin.from('profiles').upsert({ user_id: data.user.id, full_name: fullName, role }, { onConflict: 'user_id' })
  if (profileError) {
    console.error('profile upsert failed', profileError.code)
    return fail('The account was created but the role was not saved. Set the role in the table below.')
  }
  revalidatePath('/settings/users')
  return ok('User created', { email, tempPassword })
}

/** Admin only. An admin cannot remove their own admin role, so the team never loses its last admin by accident. */
export async function setRole(input: { userId: string; role: string }): Promise<ActionResult> {
  const me = await requireRole(['admin'])
  const parsed = z.object({ userId: z.uuid(), role: z.enum(ROLES) }).safeParse(input)
  if (!parsed.success) return fail('Choose a role.')
  if (parsed.data.userId === me.id && parsed.data.role !== 'admin') return fail('You cannot remove your own admin role. Ask another admin.')
  const admin = createAdminClient()
  const { error } = await admin.from('profiles').update({ role: parsed.data.role }).eq('user_id', parsed.data.userId)
  if (error) return fail('Could not change the role. Try again.')
  revalidatePath('/settings/users')
  return ok('Role changed')
}

/** Admin only: a new temporary password, shown once. The user must change it at next sign in. */
export async function resetPasswordForUser(input: { userId: string }): Promise<ActionResult<{ tempPassword: string }>> {
  await requireRole(['admin'])
  const parsed = z.object({ userId: z.uuid() }).safeParse(input)
  if (!parsed.success) return fail('User not found.')
  const admin = createAdminClient()
  const { data: existing, error: getError } = await admin.auth.admin.getUserById(parsed.data.userId)
  if (getError || !existing.user) return fail('User not found.')
  const tempPassword = generateTempPassword()
  const { error } = await admin.auth.admin.updateUserById(parsed.data.userId, {
    password: tempPassword,
    ...flagUpdate(existing.user.app_metadata, true),
  })
  if (error) return fail('Could not reset the password. Try again.')
  revalidatePath('/settings/users')
  return ok('Password reset', { tempPassword })
}

/** Admin only: disable (ban) or re-enable an account. A disabled user is signed out everywhere. */
export async function setDisabled(input: { userId: string; disabled: boolean }): Promise<ActionResult> {
  const me = await requireRole(['admin'])
  const parsed = z.object({ userId: z.uuid(), disabled: z.boolean() }).safeParse(input)
  if (!parsed.success) return fail('User not found.')
  if (parsed.data.userId === me.id) return fail('You cannot disable your own account.')
  const admin = createAdminClient()
  const { error } = await admin.auth.admin.updateUserById(parsed.data.userId, { ban_duration: parsed.data.disabled ? '876000h' : 'none' })
  if (error) return fail('Could not change the account. Try again.')
  revalidatePath('/settings/users')
  return ok(parsed.data.disabled ? 'User disabled' : 'User enabled')
}
