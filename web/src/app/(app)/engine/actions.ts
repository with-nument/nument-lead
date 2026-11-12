'use server'

import { revalidatePath, updateTag } from 'next/cache'
import { z } from 'zod'
import { requireRole } from '@/lib/auth'
import { TAGS } from '@/lib/cache-tags'
import { createClient, type ServerClient } from '@/lib/supabase/server'
import { fail, fieldErrorsOf, ok, SAVE_FAILED, type ActionResult } from '@/lib/action-result'
import type { Json } from '@/lib/database.types'
import { dispatchWorkflow, WORKFLOWS } from '@/lib/github'

// Engine settings (plan 15.6.8). Admin only: every action checks the role and RLS checks it again.

async function setMapKey(sb: ServerClient, key: 'segments_enabled' | 'sources_enabled', name: string, on: boolean) {
  const { data } = await sb.from('settings').select('value').eq('key', key).maybeSingle()
  const map = data?.value && typeof data.value === 'object' && !Array.isArray(data.value) ? (data.value as Record<string, Json>) : {}
  await sb.from('settings').update({ value: { ...map, [name]: on } }).eq('key', key)
}

const Slug = z.string().regex(/^[a-z0-9:_-]{1,60}$/)

export async function setSegmentEnabled(input: { id: string; enabled: boolean }): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = z.object({ id: Slug, enabled: z.boolean() }).safeParse(input)
  if (!parsed.success) return fail('Segment not found.')
  const sb = await createClient()
  const { error } = await sb.from('segments').update({ enabled: parsed.data.enabled }).eq('id', parsed.data.id)
  if (error) return fail(SAVE_FAILED)
  await setMapKey(sb, 'segments_enabled', parsed.data.id, parsed.data.enabled)
  updateTag(TAGS.segments)
  revalidatePath('/engine')
  return ok(parsed.data.enabled ? 'Segment on' : 'Segment off')
}

export async function setSegmentQuota(input: { id: string; quota: number }): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = z.object({ id: Slug, quota: z.coerce.number().int().min(0).max(5000) }).safeParse(input)
  if (!parsed.success) return fail('Use a whole number from 0 to 5,000.')
  const sb = await createClient()
  const { error } = await sb.from('segments').update({ daily_quota: parsed.data.quota }).eq('id', parsed.data.id)
  if (error) return fail(SAVE_FAILED)
  updateTag(TAGS.segments)
  revalidatePath('/engine')
  return ok('Daily quota saved')
}

const Budget = z.object({
  daily_cap_inr: z.coerce.number().min(0, 'Use 0 or more.').max(100_000, 'That cap looks too high.'),
  alert_pct: z.coerce.number().int().min(1, 'Use 1 to 100.').max(100, 'Use 1 to 100.'),
  research_per_day: z.coerce.number().int().min(0, 'Use 0 or more.').max(5000, 'Use at most 5,000.'),
})

export async function saveBudget(_: unknown, formData: FormData): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = Budget.safeParse(Object.fromEntries(formData))
  if (!parsed.success) return fail('Check the highlighted fields.', fieldErrorsOf(parsed.error))
  const sb = await createClient()
  const results = await Promise.all(
    (Object.keys(parsed.data) as (keyof typeof parsed.data)[]).map((key) => sb.from('settings').update({ value: parsed.data[key] }).eq('key', key)),
  )
  updateTag(TAGS.budget)
  if (results.some((r) => r.error)) return fail(SAVE_FAILED)
  revalidatePath('/engine')
  return ok('Budget saved')
}

export async function setSourceEnabled(input: { source: string; enabled: boolean }): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = z.object({ source: Slug, enabled: z.boolean() }).safeParse(input)
  if (!parsed.success) return fail('Source not found.')
  const sb = await createClient()
  const { error } = await sb.from('source_health').update({ enabled: parsed.data.enabled }).eq('source', parsed.data.source)
  if (error) return fail(SAVE_FAILED)
  if (!parsed.data.source.startsWith('llm:')) await setMapKey(sb, 'sources_enabled', parsed.data.source, parsed.data.enabled)
  revalidatePath('/engine')
  return ok(parsed.data.enabled ? 'Source on' : 'Source off')
}

const RunInput = z.object({
  kind: z.enum(Object.keys(WORKFLOWS) as [keyof typeof WORKFLOWS, ...(keyof typeof WORKFLOWS)[]]),
  dryRun: z.boolean(),
  limit: z.union([z.literal(''), z.coerce.number().int().min(1).max(5000)]),
  segment: z.union([z.literal(''), Slug]),
})

/** Starts a GitHub Actions run (workflow_dispatch). The token stays on the server. */
export async function triggerRun(input: { kind: string; dryRun: boolean; limit: string; segment: string }): Promise<ActionResult> {
  await requireRole(['admin'])
  const parsed = RunInput.safeParse(input)
  if (!parsed.success) return fail('Check the run options.')
  const { kind, dryRun, limit, segment } = parsed.data
  const r = await dispatchWorkflow(kind, { dryRun, limit: limit === '' ? undefined : limit, segment: segment || undefined })
  if (r.status === 0) return fail('Runs are not set up yet: GH_REPO and GH_DISPATCH_TOKEN are missing on the server.')
  if (!r.ok) return fail(`GitHub did not start the run (status ${r.status}).`)
  return ok(`${kind === 'sheet' ? 'Sheet sync' : kind === 'night' ? 'Night run' : 'Morning run'} started${dryRun ? ' as a dry run' : ''}. It appears under Runs within a minute.`)
}

const QueryInput = z.object({
  segmentId: Slug,
  query: z.string().trim().min(5, 'Describe what to look for.').max(300, 'Keep it under 300 characters.'),
})

export async function addCustomQuery(_: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireRole(['admin'])
  const parsed = QueryInput.safeParse(Object.fromEntries(formData))
  if (!parsed.success) return fail('Check the highlighted fields.', fieldErrorsOf(parsed.error))
  const sb = await createClient()
  const { error } = await sb
    .from('custom_queries')
    .insert({ segment_id: parsed.data.segmentId, query: parsed.data.query, status: 'new', created_by: user.id })
  if (error) return fail(SAVE_FAILED)
  revalidatePath('/engine')
  return ok("Added to tonight's queue")
}
