'use server'

import { revalidatePath } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { createClient } from '@/lib/supabase/server'
import { fail, fieldErrorsOf, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'

const Post = z.object({
  url: z.union([z.literal(''), z.url('Paste the full link, starting with https://').max(500)]),
  text: z.string().trim().min(20, 'Paste the post text (at least 20 characters).').max(5000, 'Keep it under 5,000 characters.'),
  segmentId: z.union([z.literal(''), z.string().regex(/^[a-z0-9-]{1,40}$/)]),
})

/**
 * A public post pasted by hand (plan 15.6.9). The engine never opens LinkedIn or X links: it works
 * from this text and looks the business up on allowed sources.
 */
export async function addInboxPost(_: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = Post.safeParse(Object.fromEntries(formData))
  if (!parsed.success) return fail('Check the highlighted fields.', fieldErrorsOf(parsed.error))
  const sb = await createClient()
  const { error } = await sb.from('inbox_posts').insert({
    url: parsed.data.url || null,
    text: parsed.data.text,
    segment_id: parsed.data.segmentId || null,
    status: 'new',
    created_by: user.id,
  })
  if (error) return fail(SAVE_FAILED)
  revalidatePath('/inbox')
  return ok('Added. The next night run researches it.')
}
