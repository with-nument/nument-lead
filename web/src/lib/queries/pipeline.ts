import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { CLOSED_STAGE_LIST } from '@/lib/stages'
import type { DealCurrency } from '@/lib/outcomes'
import { getMoney } from './leads'

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
  retainer?: number | null
  currency?: DealCurrency
}

/**
 * Cards for the board: every lead past New (new leads live on Today). Runs as the user and without money,
 * so the page can start it before the role is known; admins add deal values with `withBoardDealValues`.
 */
export async function getBoard(f: BoardFilters, ctx: { userId: string; today: string }): Promise<BoardCard[]> {
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
  return rows.map((r) => ({
    id: r.id!,
    name: r.name ?? 'Unnamed business',
    city: r.city,
    grade: r.grade,
    stage: r.stage ?? 'contacted',
    nextStep: r.next_step,
    dueAt: r.due_at,
    ownerId: r.owner_id,
  }))
}

/** Deal values, retainers and currencies on the cards. Admins only: call it after the role check. */
export async function withBoardDealValues(cards: BoardCard[]): Promise<BoardCard[]> {
  const money = await getMoney(await createClient(), cards.map((c) => c.id))
  return cards.map((c) => {
    const m = money.get(c.id)
    return { ...c, dealValue: m?.deal ?? null, retainer: m?.retainer ?? null, currency: m?.currency ?? 'INR' }
  })
}
