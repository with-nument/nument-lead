import 'server-only'
import { createClient } from '@supabase/supabase-js'
import type { Database } from '@/lib/database.types'
import { env } from '@/lib/env'

/**
 * Service-role client. Bypasses Row Level Security, so only call it after `requireRole(...)`
 * has checked the caller, and only for the few writes the app user cannot make
 * (auth admin calls, deal value, undoing a wrong-contact mark).
 */
export function createAdminClient() {
  const { SUPABASE_URL, NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY } = env()
  if (!SUPABASE_SERVICE_ROLE_KEY) throw new Error('SUPABASE_SERVICE_ROLE_KEY is not set on the server.')
  return createClient<Database>(SUPABASE_URL ?? NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  })
}
