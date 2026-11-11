import { NextResponse, type NextRequest } from 'next/server'
import type { EmailOtpType } from '@supabase/supabase-js'
import { createClient } from '@/lib/supabase/server'

const OTP_TYPES: EmailOtpType[] = ['recovery', 'invite', 'magiclink', 'signup', 'email_change', 'email']

const safeNext = (next: string | null) => (next && next.startsWith('/') && !next.startsWith('//') ? next : '/')

/**
 * Landing point for links in Supabase emails. Supports both link styles:
 * `?token_hash=...&type=recovery` (custom email template) and `?code=...` (default PKCE template).
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url)
  const next = safeNext(searchParams.get('next'))
  const tokenHash = searchParams.get('token_hash')
  const type = searchParams.get('type') as EmailOtpType | null
  const code = searchParams.get('code')
  const supabase = await createClient()

  if (tokenHash && type && OTP_TYPES.includes(type)) {
    const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash })
    if (!error) return NextResponse.redirect(`${origin}${next}`)
  } else if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) return NextResponse.redirect(`${origin}${next}`)
  }
  return NextResponse.redirect(`${origin}/login?error=link`)
}
