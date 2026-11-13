import 'server-only'
import { createClient, type ServerClient } from '@/lib/supabase/server'
import { applyLeadFilters, PAGE_SIZE, SORTS, type FilterContext, type LeadFilters } from '@/lib/leads-filters'
import { isDealCurrency, type LeadMoney } from '@/lib/outcomes'

const LIST_COLUMNS =
  'id, business_id, name, segment_id, country, city, website, web_domain, grade, total, stage, pitch_mode, angle, test_group, top_signal_type, top_signal_quote, top_signal_url, top_signal_at, phone_e164, phone_type, contact_name, owner_id, next_step, due_at, wa_at, last_activity_at, created_at' as const

/**
 * One page of leads. Money never comes from this query: admins get deal values from the admin view
 * with `withDealValues`. Runs as the user, so the page can start it before the role is known.
 */
export async function getLeadsPage(f: LeadFilters, ctx: FilterContext) {
  const sb = await createClient()
  const sort = SORTS[f.sort]
  const from = (f.page - 1) * PAGE_SIZE
  const { data, error, count } = await applyLeadFilters(sb.from('v_leads_caller').select(LIST_COLUMNS, { count: 'exact' }), f, ctx)
    .order(sort.column, { ascending: f.dir === 'asc', nullsFirst: false })
    .order('id', { ascending: true })
    .range(from, from + PAGE_SIZE - 1)
  if (error) throw error
  const rows = (data ?? []).flatMap((r) => (r.id ? [{ ...r, id: r.id, name: r.name ?? 'Unnamed business', stage: r.stage ?? 'new' }] : []))
  return {
    rows: rows.map((r) => ({ ...r, deal_value_inr: undefined as number | null | undefined })),
    total: count ?? rows.length,
    page: f.page,
    pageSize: PAGE_SIZE,
  }
}

/** Adds deal values to a page of leads. Admins only: call it after the role check. */
export async function withDealValues(page: Awaited<ReturnType<typeof getLeadsPage>>) {
  const money = await getDealValues(await createClient(), page.rows.map((r) => r.id))
  return { ...page, rows: page.rows.map((r) => ({ ...r, deal_value_inr: money.get(r.id) ?? null })) }
}

export type LeadListRow = Awaited<ReturnType<typeof getLeadsPage>>['rows'][number]

/** Deal values for admins. The admin view returns no rows for anyone else. */
export async function getDealValues(sb: ServerClient, leadIds: string[]) {
  const money = await getMoney(sb, leadIds)
  return new Map([...money].map(([id, m]) => [id, m.deal]))
}

/** Deal value, monthly retainer and its currency, for admins. The admin view returns no rows for anyone else. */
export async function getMoney(sb: ServerClient, leadIds: string[]) {
  const out = new Map<string, LeadMoney>()
  const ids = [...new Set(leadIds)]
  const chunks: string[][] = []
  for (let i = 0; i < ids.length; i += 150) chunks.push(ids.slice(i, i + 150))
  const amount = (v: number | null) => (v === null ? null : Number(v))
  // Chunks keep the URL short; they run side by side, not one after another.
  const parts = await Promise.all(
    chunks.map((chunk) => sb.from('v_leads_admin').select('id, deal_value_inr, retainer_monthly_value, deal_currency').in('id', chunk)),
  )
  for (const { data, error } of parts) {
    if (error) throw error
    for (const r of data ?? []) {
      if (r.id) out.set(r.id, { deal: amount(r.deal_value_inr), retainer: amount(r.retainer_monthly_value), currency: isDealCurrency(r.deal_currency) ? r.deal_currency : 'INR' })
    }
  }
  return out
}

export const EXPORT_LIMIT = 5000

const EXPORT_COLUMNS =
  'id, name, segment_id, country, city, website, category, grade, total, stage, pitch_mode, angle, test_group, top_signal_type, top_signal_quote, top_signal_url, top_signal_at, contact_name, contact_role, phone_e164, phone_type, phone_source, email, owner_id, next_step, due_at, wa_at, created_at, last_activity_at, message' as const

/** Rows for the CSV export: the same filters as the page (or the selected ids), up to 5,000 rows. */
export async function getLeadsForExport(f: LeadFilters, ctx: FilterContext & { withMoney: boolean }, ids?: string[]) {
  const sb = await createClient()
  const sort = SORTS[f.sort]
  const base = sb.from('v_leads_caller').select(EXPORT_COLUMNS)
  const query = ids?.length ? base.in('id', ids.slice(0, 500)) : applyLeadFilters(base, f, ctx)
  const { data, error } = await query.order(sort.column, { ascending: f.dir === 'asc', nullsFirst: false }).limit(EXPORT_LIMIT)
  if (error) throw error
  const rows = (data ?? []).filter((r) => r.id)
  if (!ctx.withMoney) return rows
  const money = await getDealValues(sb, rows.map((r) => r.id!))
  return rows.map((r) => ({ ...r, deal_value_inr: money.get(r.id!) ?? null }))
}

/**
 * Distinct cities for the filter, limited to the chosen countries. The city of a lead is its business's
 * city (as in v_leads_caller), so this reads leads with their business only, not the whole view.
 */
export async function getCities(countries: string[]) {
  const sb = await createClient()
  let q = sb.from('leads').select('businesses!inner(city)').not('businesses.city', 'is', null).limit(5000)
  if (countries.length) q = q.in('businesses.country', countries)
  const { data, error } = await q
  if (error) throw error
  return [...new Set((data ?? []).map((r) => r.businesses?.city?.trim()).filter((c): c is string => Boolean(c)))].sort((a, b) => a.localeCompare(b))
}

/** Saved views: mine first, then the ones teammates shared. */
export async function getSavedViews(userId: string) {
  const sb = await createClient()
  const { data, error } = await sb.from('saved_views').select('id, user_id, name, query, shared, created_at').order('name')
  if (error) throw error
  const views = (data ?? []).map((v) => ({
    id: v.id,
    name: v.name,
    shared: v.shared,
    mine: v.user_id === userId,
    qs: typeof (v.query as { qs?: unknown } | null)?.qs === 'string' ? ((v.query as { qs: string }).qs) : '',
  }))
  return { mine: views.filter((v) => v.mine), shared: views.filter((v) => !v.mine && v.shared) }
}
