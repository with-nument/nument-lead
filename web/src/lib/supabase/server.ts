import 'server-only'
import { cache } from 'react'
import { cookies } from 'next/headers'
import { connection } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import type { Database } from '@/lib/database.types'
import { env } from '@/lib/env'
import { timedFetch } from '@/lib/perf'

/**
 * Supabase client for Server Components, Server Actions and Route Handlers.
 * Runs as the signed-in user, so Row Level Security applies to every query.
 * One client per request while rendering (React cache), so the session cookie is read and checked
 * once, not once per query. Outside a render (actions, route handlers) every call gets a new client.
 */
export const createClient = cache(async function createClient() {
  // Request-time only: the auth client reads the clock as it loads the session, so never in a prerender
  // or a runtime prefetch. Pages start queries before the session check, so this guard lives here.
  await connection()
  const cookieStore = await cookies()
  const { NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY } = env()
  const fetch = timedFetch('server')
  return createServerClient<Database>(NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, {
    ...(fetch ? { global: { fetch } } : {}),
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (list) => {
        try {
          list.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
        } catch {
          // Called from a Server Component, where cookies are read-only. The proxy refreshes the session.
        }
      },
    },
  })
})

export type ServerClient = Awaited<ReturnType<typeof createClient>>
