'use server'

import { redirect } from 'next/navigation'
import { z } from 'zod'
import { getSessionUser } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { mustChangePassword } from '@/lib/password-flag'
import { setPasswordFlag } from '@/lib/password-flag-server'
import { env } from '@/lib/env'
import { PasswordSchema } from '@/lib/password'
import { fieldErrorsOf } from '@/lib/action-result'

export type AuthFormState = { message?: string; ok?: boolean; fieldErrors?: Record<string, string[]> } | undefined

const Login = z.object({
  email: z.email('Enter a valid email.').max(254),
  password: z.string().min(1, 'Enter your password.').max(200),
  next: z.string().max(500).optional(),
})

/** Only same-site paths are allowed after login, so the link cannot send people elsewhere. */
function safeNext(next: string | undefined) {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/'
  return next
}

export async function login(_: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const parsed = Login.safeParse({
    email: String(formData.get('email') ?? '').trim().toLowerCase(),
    password: formData.get('password'),
    next: formData.get('next') || undefined,
  })
  if (!parsed.success) return { message: 'Enter your email and password.' }
  const supabase = await createClient()
  const { data, error } = await supabase.auth.signInWithPassword({ email: parsed.data.email, password: parsed.data.password })
  if (error) {
    if (error.status === 429) return { message: 'Too many attempts. Wait a minute and try again.' }
    // Never say whether the email or the password was wrong.
    return { message: 'Email or password is not right.' }
  }
  // A redirect from a Server Action renders the target in the same response, without the proxy,
  // so the temporary-password rule is applied here as well.
  if (mustChangePassword(data.user?.app_metadata)) redirect('/settings?change_password=1')
  redirect(safeNext(parsed.data.next))
}

export async function logout() {
  const supabase = await createClient()
  await supabase.auth.signOut({ scope: 'local' })
  redirect('/login')
}

const ResetRequest = z.object({ email: z.email('Enter a valid email.').max(254) })

export async function requestReset(_: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const parsed = ResetRequest.safeParse({ email: String(formData.get('email') ?? '').trim().toLowerCase() })
  if (!parsed.success) return { fieldErrors: fieldErrorsOf(parsed.error), message: 'Enter a valid email.' }
  const supabase = await createClient()
  const appUrl = env().NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000'
  const { error } = await supabase.auth.resetPasswordForEmail(parsed.data.email, {
    redirectTo: `${appUrl}/auth/confirm?next=/reset-password/update`,
  })
  if (error && error.status !== 429) console.error('reset request failed', error.status, error.code)
  // Same answer whether or not the email has an account.
  return { ok: true, message: 'If this email has an account, a reset link is on its way.' }
}

const NewPassword = z
  .object({ password: PasswordSchema, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { message: 'The two passwords do not match.', path: ['confirm'] })

/** Sets a new password after the email link and clears the temporary-password flag. */
export async function updatePassword(_: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const parsed = NewPassword.safeParse({ password: formData.get('password'), confirm: formData.get('confirm') })
  if (!parsed.success) return { fieldErrors: fieldErrorsOf(parsed.error), message: 'Check the highlighted fields.' }
  const user = await getSessionUser()
  if (!user) return { message: 'That link has expired. Ask for a new one.' }
  const supabase = await createClient()
  const { error } = await supabase.auth.updateUser({ password: parsed.data.password })
  if (error) {
    if (error.code === 'same_password') return { fieldErrors: { password: ['Choose a password you have not used here before.'] } }
    if (error.code === 'weak_password') return { fieldErrors: { password: ['Choose a stronger password.'] } }
    return { message: 'Could not save the new password. Try again.' }
  }
  // Only after the user's own password change succeeded; app_metadata needs the service role.
  if (user.mustChangePassword) {
    try {
      await setPasswordFlag(user.id, false)
    } catch (e) {
      console.error(e)
      return { message: 'Your password was saved, but we could not finish signing you in. Sign in again with the new password.' }
    }
  }
  // New token, so the proxy sees the cleared flag at once.
  await supabase.auth.refreshSession()
  redirect('/')
}
