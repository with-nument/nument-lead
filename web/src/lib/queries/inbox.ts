import 'server-only'
import { createClient } from '@/lib/supabase/server'

export async function getInboxPosts() {
  const sb = await createClient()
  const { data, error } = await sb
    .from('inbox_posts')
    .select('id, url, text, segment_id, status, lead_id, created_by, created_at')
    .order('created_at', { ascending: false })
    .limit(100)
  if (error) throw error
  return data ?? []
}
