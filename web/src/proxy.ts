import { NextResponse, type NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/proxy'
import { isV2, UI_COOKIE, v2PathFor } from '@/lib/ui-flag'

export async function proxy(request: NextRequest) {
  const response = await updateSession(request)
  // Sign-in and temporary-password redirects always win; only a request that goes on can show v2.
  if (response.headers.has('location') || !isV2(request.cookies.get(UI_COOKIE)?.value)) return response
  const target = v2PathFor(request.nextUrl.pathname)
  if (!target) return response
  // New design: render the v2 screen while the address bar keeps the normal URL. The request headers
  // carry any session cookies updateSession just refreshed, and the refreshed cookies go back to the browser.
  const url = request.nextUrl.clone()
  url.pathname = target
  const rewrite = NextResponse.rewrite(url, { request: { headers: request.headers } })
  response.cookies.getAll().forEach((c) => rewrite.cookies.set(c))
  return rewrite
}

export const config = {
  matcher: [
    // Everything except static files, images, fonts, app icons and the health check (Render calls it
    // every few seconds and it never needs a session).
    '/((?!_next/static|_next/image|api/health|favicon.ico|icon.svg|apple-icon.png|manifest.webmanifest|robots.txt|.*\\.(?:svg|png|jpg|jpeg|webp|ico|woff2?|map)$).*)',
  ],
}
