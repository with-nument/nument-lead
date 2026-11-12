import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { CLOSED_STAGE_LIST } from '@/lib/stages'
import { getDealValues } from './leads'

export type BoardFilters = { seg: string; country: string; owner: string; overdue: boolean }

export type BoardCard = {
  id: string
  name: string
  city: string | null
  grade: string | null
  stage: string
  nextStep: string | null
  dueAt: string | null
  ownerId: string | null
  dealValue?: number | null
}

/** Cards for the board: every lead past New (new leads live on Today). */
export async function getBoard(f: BoardFilters, ctx: { userId: string; today: string; withMoney: boolean }): Promise<BoardCard[]> {
  const sb = await createClient()
  let q = sb
    .from('v_leads_caller')
    .select('id, name, city, grade, stage, next_step, due_at, owner_id, segment_id, country, last_activity_at')
    .neq('stage', 'new')
  if (f.seg) q = q.eq('segment_id', f.seg)
  if (f.country) q = q.eq('country', f.country)
  if (f.owner === 'me') q = q.eq('owner_id', ctx.userId)
  else if (f.owner === 'none') q = q.is('owner_id', null)
  else if (f.owner) q = q.eq('owner_id', f.owner)
  if (f.overdue) q = q.lt('due_at', ctx.today).not('stage', 'in', CLOSED_STAGE_LIST)
  const { data, error } = await q.order('last_activity_at', { ascending: false }).limit(1000)
  if (error) throw error
  const rows = (data ?? []).filter((r) => r.id)
  const money = ctx.withMoney ? await getDealValues(sb, rows.map((r) => r.id!)) : null
  return rows.map((r) => ({
    id: r.id!,
    name: r.name ?? 'Unnamed business',
    city: r.city,
    grade: r.grade,
    stage: r.stage ?? 'contacted',
    nextStep: r.next_step,
    dueAt: r.due_at,
    ownerId: r.owner_id,
    ...(money ? { dealValue: money.get(r.id!) ?? null } : {}),
  }))
}
