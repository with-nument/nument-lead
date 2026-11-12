import 'server-only'
import { createAdminClient } from '@/lib/supabase/admin'

/**
 * Finish time of the last successful sheet sync, for the top bar. Runs are admin-only under RLS;
 * this one timestamp is shown to everyone, so it is read with the service role after the session check.
 */
export async function getLastSheetSync(): Promise<string | null> {
  try {
    const admin = createAdminClient()
    const { data } = await admin
      .from('runs')
      .select('finished_at, started_at')
      .eq('kind', 'sheet_sync')
      .eq('status', 'ok')
      .order('started_at', { ascending: false })
      .limit(1)
      .maybeSingle()
    return data?.finished_at ?? data?.started_at ?? null
  } catch (e) {
    console.error('last sheet sync lookup failed', e)
    return null
  }
}
