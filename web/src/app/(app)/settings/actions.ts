'use server'

import { revalidatePath, updateTag } from 'next/cache'
import { redirect } from 'next/navigation'
import { z } from 'zod'
import { requireUser } from '@/lib/auth'
import { TAGS } from '@/lib/cache-tags'
import { createClient } from '@/lib/supabase/server'
import { fail, fieldErrorsOf, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import { PasswordSchema } from '@/lib/password'
import { setPasswordFlag } from '@/lib/password-flag-server'

const Name = z.object({ fullName: z.string().trim().min(2, 'Use at least 2 characters.').max(80, 'Use at most 80 characters.') })

export async function updateProfile(_: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser()
  const parsed = Name.safeParse({ fullName: formData.get('fullName') })
  if (!parsed.success) return fail('Check your name.', fieldErrorsOf(parsed.error))
  const sb = await createClient()
  const { error } = await sb.from('profiles').update({ full_name: parsed.data.fullName }).eq('user_id', user.id)
  if (error) return fail(SAVE_FAILED)
  updateTag(TAGS.team)
  revalidatePath('/', 'layout')
  return ok('Name saved')
}

const NewPassword = z
  .object({ password: PasswordSchema, confirm: z.string(), forced: z.string().optional() })
  .refine((v) => v.password === v.confirm, { message: 'The two passwords do not match.', path: ['confirm'] })

/** Changes the signed-in user's password and clears the temporary-password flag. */
export async function changePassword(_: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser()
  const parsed = NewPassword.safeParse(Object.fromEntries(formData))
  if (!parsed.success) return fail('Check the highlighted fields.', fieldErrorsOf(parsed.error))
  const sb = await createClient()
  const { error } = await sb.auth.updateUser({ password: parsed.data.password })
  if (error) {
    if (error.code === 'same_password') return fail('Choose a password you have not used here before.', { password: ['Choose a new password.'] })
    if (error.code === 'weak_password') return fail('Choose a stronger password.', { password: ['Choose a stronger password.'] })
    if (error.code === 'reauthentication_needed') return fail('For safety, sign out, sign in again, then change your password.')
    return fail('Could not change the password. Try again.')
  }
  // The flag lives in app_metadata, which only the service role can change: clear it here, after
  // the user's own password change succeeded, then refresh so the new token no longer carries it.
  if (user.mustChangePassword) {
    try {
      await setPasswordFlag(user.id, false)
    } catch (e) {
      console.error(e)
      return fail('Your password was saved, but we could not finish. Sign out and sign in with the new password.')
    }
  }
  await sb.auth.refreshSession()
  if (parsed.data.forced === '1') redirect('/')
  return ok('Password changed')
}

/** Signs out every other browser and phone where this account is signed in. */
export async function signOutOtherSessions(): Promise<ActionResult> {
  await requireUser()
  const sb = await createClient()
  const { error } = await sb.auth.signOut({ scope: 'others' })
  if (error) return fail('Could not sign out the other sessions. Try again.')
  return ok('Signed out everywhere else')
}
