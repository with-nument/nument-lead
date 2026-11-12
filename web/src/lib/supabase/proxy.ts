import { NextResponse, type NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import type { Database } from '@/lib/database.types'
import { mustChangePassword } from '@/lib/password-flag'

/** Paths anyone can open. Everything else needs a session. */
export const PUBLIC_PATHS = ['/login', '/reset-password', '/auth/confirm', '/api/health'] as const

export function isPublicPath(path: string) {
  return PUBLIC_PATHS.some((p) => path === p || path.startsWith(`${p}/`))
}

/**
 * Refreshes the Supabase session on every request and applies the optimistic routing rules:
 * no session goes to /login, a signed-in user never sees /login, and a user with a temporary
 * password is sent to /settings until it is changed. Pages and actions check again (requireRole).
 */
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request })

  const supabase = createServerClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (list) => {
          list.forEach(({ name, value }) => request.cookies.set(name, value))
          response = NextResponse.next({ request })
          list.forEach(({ name, value, options }) => response.cookies.set(name, value, options))
        },
      },
    },
  )

  // getClaims() refreshes an expired session and verifies the JWT signature locally (asymmetric keys).
  const { data } = await supabase.auth.getClaims()
  const claims = data?.claims
  const path = request.nextUrl.pathname
  const publicPath = isPublicPath(path)

  const redirectTo = (pathname: string, params?: Record<string, string>) => {
    const url = request.nextUrl.clone()
    url.pathname = pathname
    url.search = ''
    for (const [k, v] of Object.entries(params ?? {})) url.searchParams.set(k, v)
    const redirect = NextResponse.redirect(url)
    // Keep any refreshed session cookies.
    response.cookies.getAll().forEach((c) => redirect.cookies.set(c))
    return redirect
  }

  if (!claims && !publicPath) {
    const next = `${path}${request.nextUrl.search}`
    return redirectTo('/login', next === '/' ? undefined : { next })
  }
  if (claims && path === '/login') return redirectTo('/')

  if (claims && mustChangePassword(claims.app_metadata) && !publicPath && path !== '/settings') {
    return redirectTo('/settings', { change_password: '1' })
  }

  return response
}
