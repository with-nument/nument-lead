import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { addDays, istDate, istMidnightUtc } from '@/lib/dates'

export const BUDGET_KEYS = ['daily_cap_inr', 'alert_pct', 'research_per_day'] as const
export type BudgetKey = (typeof BUDGET_KEYS)[number]

/** Everything the Engine page shows. Admin only (the page checks the role, RLS checks again). */
export async function getEngineOverview() {
  const sb = await createClient()
  const today = istDate()
  const yesterday = addDays(today, -1)
  const [segments, settings, sources, runs, queries, spend, researched, created] = await Promise.all([
    sb.from('segments').select('id, display_name, domain, country, enabled, daily_quota, updated_at').order('id'),
    sb.from('settings').select('key, value').in('key', [...BUDGET_KEYS]),
    sb
      .from('v_source_health')
      .select('source, enabled, last_ok_at, last_error_at, last_error, blocked_until, requests_today, health')
      .order('source'),
    sb.from('runs').select('id, kind, started_at, finished_at, status, stats, error').order('started_at', { ascending: false }).limit(20),
    sb.from('custom_queries').select('id, segment_id, query, status, created_at').order('created_at', { ascending: false }).limit(50),
    sb.from('v_costs_daily').select('inr').eq('day', today),
    sb
      .from('businesses')
      .select('segment_id')
      .gte('researched_at', istMidnightUtc(yesterday))
      .lt('researched_at', istMidnightUtc(today))
      .limit(5000),
    sb
      .from('v_leads_caller')
      .select('segment_id')
      .gte('created_at', istMidnightUtc(yesterday))
      .lt('created_at', istMidnightUtc(today))
      .limit(5000),
  ])
  for (const r of [segments, settings, sources, runs, queries]) if (r.error) throw r.error

  const count = (rows: { segment_id: string | null }[] | null) => {
    const m = new Map<string, number>()
    for (const r of rows ?? []) if (r.segment_id) m.set(r.segment_id, (m.get(r.segment_id) ?? 0) + 1)
    return m
  }
  const researchedBy = count(researched.data)
  const leadsBy = count(created.data)
  const setting = (key: BudgetKey, fallback: number) => {
    const v = Number(settings.data?.find((s) => s.key === key)?.value)
    return Number.isFinite(v) ? v : fallback
  }

  return {
    segments: (segments.data ?? []).map((s) => ({
      ...s,
      researchedYesterday: researchedBy.get(s.id) ?? 0,
      leadsYesterday: leadsBy.get(s.id) ?? 0,
    })),
    budget: {
      daily_cap_inr: setting('daily_cap_inr', 750),
      alert_pct: setting('alert_pct', 80),
      research_per_day: setting('research_per_day', 300),
    },
    spendToday: (spend.data ?? []).reduce((sum, r) => sum + Number(r.inr ?? 0), 0),
    sources: sources.data ?? [],
    runs: runs.data ?? [],
    queries: queries.data ?? [],
  }
}
