import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { applyLeadFilters, PAGE_SIZE, SORTS, type FilterContext, type LeadFilters } from '@/lib/leads-filters'
import { leadsFiltersJson, toLeadsPage, type LeadsPage } from './page-data'

export type { LeadListRow, LeadsPage, SavedView } from './page-data'

/**
 * One page of leads in one database call (leads_page, migration 0024): the rows, the total, the cities for the
 * filter (in the chosen countries) and the saved views (the user's own and the shared ones). Runs as the user
 * (Row Level Security), so the page can start it before the role is known; admins get deal_value_inr on each
 * row, read through the admin view. Without filters the total is a plain count of leads.
 */
export async function getLeadsPage(f: LeadFilters): Promise<LeadsPage> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('leads_page', { filters: leadsFiltersJson(f), page: f.page, page_size: PAGE_SIZE })
  if (error) throw error
  return toLeadsPage(data, { page: f.page, pageSize: PAGE_SIZE })
}

export const EXPORT_LIMIT = 5000

const EXPORT_COLUMNS =
  'id, name, segment_id, country, city, website, category, grade, total, stage, pitch_mode, angle, test_group, top_signal_type, top_signal_quote, top_signal_url, top_signal_at, contact_name, contact_role, phone_e164, phone_type, phone_source, email, owner_id, next_step, due_at, wa_at, created_at, last_activity_at, message' as const

/**
 * Rows for the CSV export: the same filters as the page (or the selected ids), up to 5,000 rows. Admins read
 * the admin view, which has the same columns plus the money, so the deal values come in the same request; it
 * returns nothing to anyone the database does not know as an admin.
 */
export async function getLeadsForExport(f: LeadFilters, ctx: FilterContext & { withMoney: boolean }, ids?: string[]) {
  const sb = await createClient()
  const sort = SORTS[f.sort]
  if (ctx.withMoney) {
    const base = sb.from('v_leads_admin').select(`${EXPORT_COLUMNS}, deal_value_inr`)
    const query = ids?.length ? base.in('id', ids.slice(0, 500)) : applyLeadFilters(base, f, ctx)
    const { data, error } = await query.order(sort.column, { ascending: f.dir === 'asc', nullsFirst: false }).limit(EXPORT_LIMIT)
    if (error) throw error
    return (data ?? []).filter((r) => r.id)
  }
  const base = sb.from('v_leads_caller').select(EXPORT_COLUMNS)
  const query = ids?.length ? base.in('id', ids.slice(0, 500)) : applyLeadFilters(base, f, ctx)
  const { data, error } = await query.order(sort.column, { ascending: f.dir === 'asc', nullsFirst: false }).limit(EXPORT_LIMIT)
  if (error) throw error
  return (data ?? []).filter((r) => r.id)
}
