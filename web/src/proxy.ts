import type { NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/proxy'

export async function proxy(request: NextRequest) {
  return updateSession(request)
}

export const config = {
  matcher: [
    // Everything except static files, images and app icons.
    '/((?!_next/static|_next/image|favicon.ico|icon.svg|apple-icon.png|manifest.webmanifest|.*\\.(?:svg|png|jpg|jpeg|webp|ico)$).*)',
  ],
}
