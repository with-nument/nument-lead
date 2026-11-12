import type { NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/proxy'

export async function proxy(request: NextRequest) {
  return updateSession(request)
}

export const config = {
  matcher: [
    // Everything except static files, images, fonts, app icons and the health check (Render calls it
    // every few seconds and it never needs a session).
    '/((?!_next/static|_next/image|api/health|favicon.ico|icon.svg|apple-icon.png|manifest.webmanifest|robots.txt|.*\\.(?:svg|png|jpg|jpeg|webp|ico|woff2?|map)$).*)',
  ],
}
