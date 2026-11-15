// What the one-call-per-page database functions return (supabase/migrations/0024_page_reads.sql), as types,
// and the small conversions from their JSON to what the pages use. Pure: no server or network access, so it can
// be unit tested and shared by the v1 pages and the new ones. The functions run as the signed-in user, so Row
// Level Security has already decided every row; money fields are present only for admins.
import type { Json } from '@/lib/database.types'
import type { LeadFilters } from '@/lib/leads-filters'
import { isDealCurrency, type DealCurrency, type LeadMoney } from '@/lib/outcomes'

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : {})
const list = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])
const count = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : Number(v) || 0)
/** A JSON number or numeric string as a number; null for null, missing or not a number. */
export const amount = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}
const currency = (v: unknown): DealCurrency => (isDealCurrency(v) ? v : 'INR')

/* ------------------------------------------------------------------------------------------------------------
 * Today: home_summary()
 * ---------------------------------------------------------------------------------------------------------- */

export type TodayKpis = {
  ready: number
  contactedThisWeek: number
  talking: number
  discovery: number
  proposals: number
  overdue: number
  /** Admins only (null for everyone else): money won this month, in rupees. */
  wonThisMonthInr: number | null
}

/** A row of the send list: v_today's columns. */
export type SendRow = {
  lead_id: string
  company: string
  city: string | null
  country: string | null
  segment_id: string | null
  grade: string | null
  total: number | null
  channel: string | null
  top_signal_type: string | null
  top_signal_quote: string | null
  top_signal_url: string | null
  top_signal_at: string | null
  contact_name: string | null
  contact_role: string | null
  phone_e164: string | null
  phone_type: string | null
  phone_source: string | null
  email: string | null
  email_subject: string | null
  email_body: string | null
  message: string | null
}

/** A day 3 or day 7 follow-up due today or earlier, with the business's city and the shown phone's type. */
export type FollowupRow = {
  lead_id: string
  company: string
  segment_id: string | null
  grade: string | null
  contact_name: string | null
  phone_e164: string | null
  which: 'd3' | 'd7'
  followup_text: string | null
  due_on: string
  city: string | null
  phone_type: string | null
}

export type HomeSummary = { kpis: TodayKpis; send: SendRow[]; followups: FollowupRow[] }

export function toHomeSummary(data: Json | null): HomeSummary {
  const d = obj(data)
  const c = obj(d.counts)
  return {
    kpis: {
      ready: count(c.ready),
      contactedThisWeek: count(c.contacted_this_week),
      talking: count(c.talking),
      discovery: count(c.discovery),
      proposals: count(c.proposals),
      overdue: count(c.overdue),
      wonThisMonthInr: amount(d.won_this_month_inr),
    },
    send: list<SendRow>(d.send),
    followups: list<FollowupRow>(d.followups).filter((f) => f.which === 'd3' || f.which === 'd7'),
  }
}

/* ------------------------------------------------------------------------------------------------------------
 * Navigation: nav_counts()
 * ---------------------------------------------------------------------------------------------------------- */

export type NavCounts = {
  /** Rows of the send list (new A and B leads, reachable, not skipped). */
  ready: number
  /** Day 3 and day 7 follow-ups due today or earlier. */
  followupsDue: number
  /** Open leads past their due date. */
  overdue: number
  /** Leads talking, in discovery or with a proposal out. */
  deals: number
  /** New Inbox posts (admins; 0 for everyone else). */
  inboxNew: number
}

export function toNavCounts(data: Json | null): NavCounts {
  const d = obj(data)
  return {
    ready: count(d.ready),
    followupsDue: count(d.followups_due),
    overdue: count(d.overdue),
    deals: count(d.deals),
    inboxNew: count(d.inbox_new),
  }
}

/* ------------------------------------------------------------------------------------------------------------
 * The lead page: lead_detail(lead_id, include_unverified)
 * ---------------------------------------------------------------------------------------------------------- */

/** Every v_leads_caller column (no money), plus lost_reason. */
export type LeadRow = {
  id: string
  business_id: string
  segment_id: string | null
  score_id: string | null
  grade: string | null
  pitch_mode: string | null
  test_group: string | null
  angle: string | null
  channel: string | null
  message: string | null
  message_alt: string | null
  email_subject: string | null
  email_body: string | null
  followup_d3: string | null
  followup_d7: string | null
  message_model: string | null
  message_check_score: number | null
  stage: string
  owner_id: string | null
  wa_at: string | null
  call_at: string | null
  d3_at: string | null
  d7_at: string | null
  meeting_at: string | null
  next_step: string | null
  due_at: string | null
  skipped_until: string | null
  regen_requested_at: string | null
  notes: string | null
  created_at: string | null
  updated_at: string | null
  last_activity_at: string | null
  name: string
  city: string | null
  locality: string | null
  country: string | null
  website: string | null
  web_domain: string | null
  category: string | null
  subcategory: string | null
  total: number | null
  judge_note: string | null
  top_signal_type: string | null
  top_signal_quote: string | null
  top_signal_url: string | null
  top_signal_at: string | null
  contact_name: string | null
  contact_role: string | null
  phone_e164: string | null
  phone_type: string | null
  phone_source: string | null
  email: string | null
  /** Why it closed; meaningful only while the stage is Lost or Not now (lib/outcomes). */
  lost_reason: string | null
}

export type LeadBusiness = {
  name: string
  website: string | null
  web_domain: string | null
  address: string | null
  place_id: string | null
  branches_count: number | null
  staff_count: number | null
  rating: number | null
  review_count: number | null
}

export type LeadContact = {
  id: string
  name: string | null
  role: string | null
  phone_e164: string | null
  phone_type: string
  email: string | null
  source: string
  source_url: string | null
  quote: string | null
  is_decision_maker: boolean
  verified: boolean
  do_not_contact: boolean
  created_at: string
  line: string
  line_why: string | null
}

export type LeadSignal = {
  id: string
  type: string
  category: string
  points: number
  observed_at: string
  expires_at: string
  source: string
  url: string | null
  quote: string | null
}

export type LeadFact = {
  id: string
  field: string
  value: Json
  quote: string | null
  url: string | null
  model: string | null
  verified: boolean
  created_at: string
}

export type LeadScore = {
  fit: number
  can_pay: number
  intent: number
  reach: number
  total: number
  grade: string
  pitch_mode: string
  reasons: Json
  judge_grade: string | null
  judge_note: string | null
  judge_model: string | null
  version: string
  computed_at: string
}

export type LeadPage = { id: string; url: string; title: string | null; fetched_at: string }
export type LeadActivity = { id: string; type: string; source: string; at: string; user_id: string | null; payload: Json }
export type LeadFeedback = { id: string; user_id: string | null; rating: number; reason: string | null; at: string }

export type LeadDetail = {
  lead: LeadRow
  business: LeadBusiness | null
  contacts: LeadContact[]
  /** Which of the contacts' numbers are on Do not contact (always empty for viewers, who cannot read it). */
  suppressedPhones: string[]
  signals: LeadSignal[]
  facts: LeadFact[]
  score: LeadScore | null
  activities: LeadActivity[]
  feedback: LeadFeedback[]
  pages: LeadPage[]
  /** Admins only: deal value (rupees), monthly retainer and its currency. Null for everyone else. */
  money: LeadMoney | null
}

/** Null when the lead does not exist or this user cannot see it. */
export function toLeadDetail(data: Json | null): LeadDetail | null {
  const d = obj(data)
  const lead = obj(d.lead)
  if (typeof lead.id !== 'string' || typeof lead.business_id !== 'string') return null
  const money = d.money && typeof d.money === 'object' ? obj(d.money) : null
  return {
    lead: {
      ...(lead as LeadRow),
      name: typeof lead.name === 'string' ? lead.name : 'Unnamed business',
      stage: typeof lead.stage === 'string' ? lead.stage : 'new',
      lost_reason: typeof lead.lost_reason === 'string' ? lead.lost_reason : null,
    },
    business: d.business && typeof d.business === 'object' ? (d.business as LeadBusiness) : null,
    contacts: list<LeadContact>(d.contacts),
    suppressedPhones: list<unknown>(d.suppressed_phones).filter((p): p is string => typeof p === 'string'),
    signals: list<LeadSignal>(d.signals),
    facts: list<LeadFact>(d.facts),
    score: d.score && typeof d.score === 'object' ? (d.score as LeadScore) : null,
    activities: list<LeadActivity>(d.activities),
    feedback: list<LeadFeedback>(d.feedback),
    pages: list<LeadPage>(d.pages),
    money: money ? { deal: amount(money.deal), retainer: amount(money.retainer), currency: currency(money.currency) } : null,
  }
}

/* ------------------------------------------------------------------------------------------------------------
 * The pipeline: deals_board(filters, max_per_stage, closed_per_stage)
 * ---------------------------------------------------------------------------------------------------------- */

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
  segmentId: string | null
  country: string | null
  lastActivityAt: string | null
  /** Admins only (undefined for everyone else). */
  dealValue?: number | null
  retainer?: number | null
  currency?: DealCurrency
}

export type Board = {
  cards: BoardCard[]
  /** Leads per stage, for every stage after New, with the same filters (however many cards came back). */
  counts: Record<string, number>
}

/** The filters as deals_board takes them: only the ones in use. */
export function boardFiltersJson(f: BoardFilters): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {}
  if (f.seg) out.seg = f.seg
  if (f.country) out.country = f.country
  if (f.owner) out.owner = f.owner
  if (f.overdue) out.overdue = true
  return out
}

/**
 * Cards and counts. The function adds money keys only for admins, and only to cards that have a deal value or a
 * retainer, so the money fields are set exactly when the JSON has them (admins render a missing value as none).
 */
export function toBoard(data: Json | null): Board {
  const d = obj(data)
  const cards = list<Obj>(d.cards).flatMap((c): BoardCard[] => {
    if (typeof c.id !== 'string') return []
    const card: BoardCard = {
      id: c.id,
      name: typeof c.name === 'string' ? c.name : 'Unnamed business',
      city: typeof c.city === 'string' ? c.city : null,
      grade: typeof c.grade === 'string' ? c.grade : null,
      stage: typeof c.stage === 'string' ? c.stage : 'contacted',
      nextStep: typeof c.next_step === 'string' ? c.next_step : null,
      dueAt: typeof c.due_at === 'string' ? c.due_at : null,
      ownerId: typeof c.owner_id === 'string' ? c.owner_id : null,
      segmentId: typeof c.segment_id === 'string' ? c.segment_id : null,
      country: typeof c.country === 'string' ? c.country : null,
      lastActivityAt: typeof c.last_activity_at === 'string' ? c.last_activity_at : null,
    }
    const money = 'deal_value_inr' in c || 'retainer_monthly_value' in c
    return [money ? { ...card, dealValue: amount(c.deal_value_inr), retainer: amount(c.retainer_monthly_value), currency: currency(c.deal_currency) } : card]
  })
  const counts: Record<string, number> = {}
  for (const [stage, n] of Object.entries(obj(d.counts))) counts[stage] = count(n)
  return { cards, counts }
}

/* ------------------------------------------------------------------------------------------------------------
 * The Leads page: leads_page(filters, page, page_size)
 * ---------------------------------------------------------------------------------------------------------- */

export type LeadListRow = {
  id: string
  business_id: string
  name: string
  segment_id: string | null
  country: string | null
  city: string | null
  website: string | null
  web_domain: string | null
  grade: string | null
  total: number | null
  stage: string
  pitch_mode: string | null
  angle: string | null
  test_group: string | null
  top_signal_type: string | null
  top_signal_quote: string | null
  top_signal_url: string | null
  top_signal_at: string | null
  phone_e164: string | null
  phone_type: string | null
  contact_name: string | null
  owner_id: string | null
  next_step: string | null
  due_at: string | null
  wa_at: string | null
  last_activity_at: string | null
  created_at: string | null
  /** Admins only (undefined for everyone else). */
  deal_value_inr?: number | null
}

export type SavedView = { id: string; name: string; shared: boolean; mine: boolean; qs: string }

export type LeadsPage = {
  rows: LeadListRow[]
  total: number
  page: number
  pageSize: number
  /** Every city with a lead (in the chosen countries), sorted the way people read them. */
  cities: string[]
  views: { mine: SavedView[]; shared: SavedView[] }
}

/** The Leads page filters as leads_page takes them: only the ones in use. */
export function leadsFiltersJson(f: LeadFilters): Record<string, string | string[] | boolean> {
  const out: Record<string, string | string[] | boolean> = {}
  if (f.q) out.q = f.q
  for (const key of ['seg', 'country', 'city', 'grade', 'signal', 'stage', 'pitch'] as const) if (f[key].length) out[key] = [...f[key]]
  if (f.mobile) out.mobile = true
  if (f.overdue) out.overdue = true
  if (f.owner) out.owner = f.owner
  if (f.from) out.from = f.from
  if (f.to) out.to = f.to
  if (f.sort !== 'created') out.sort = f.sort
  if (f.dir !== 'desc') out.dir = f.dir
  return out
}

/** One page of leads. deal_value_inr is set exactly when the function added it, which it does only for admins. */
export function toLeadsPage(data: Json | null, opts: { page: number; pageSize: number }): LeadsPage {
  const d = obj(data)
  const rows = list<Obj>(d.rows).flatMap((r): LeadListRow[] => {
    if (typeof r.id !== 'string') return []
    const row: LeadListRow = { ...(r as LeadListRow), name: typeof r.name === 'string' ? r.name : 'Unnamed business', stage: typeof r.stage === 'string' ? r.stage : 'new' }
    if ('deal_value_inr' in r) row.deal_value_inr = amount(r.deal_value_inr)
    return [row]
  })
  const views = list<Obj>(d.views).flatMap((v): SavedView[] =>
    typeof v.id === 'string' && typeof v.name === 'string'
      ? [{ id: v.id, name: v.name, shared: v.shared === true, mine: v.mine === true, qs: typeof v.qs === 'string' ? v.qs : '' }]
      : [],
  )
  const cities = list<unknown>(d.cities)
    .filter((c): c is string => typeof c === 'string' && c.trim() !== '')
    .sort((a, b) => a.localeCompare(b))
  return {
    rows,
    total: count(d.total ?? rows.length),
    page: count(d.page) || opts.page,
    pageSize: count(d.page_size) || opts.pageSize,
    cities,
    views: { mine: views.filter((v) => v.mine), shared: views.filter((v) => !v.mine && v.shared) },
  }
}

/* ------------------------------------------------------------------------------------------------------------
 * Search: search_leads(q, max)
 * ---------------------------------------------------------------------------------------------------------- */

export type SearchResult = {
  id: string
  name: string
  city: string | null
  country: string | null
  webDomain: string | null
  segmentId: string | null
  grade: string | null
  stage: string
  createdAt: string | null
}

export function toSearchResults(data: Json | null): SearchResult[] {
  return list<Obj>(data).flatMap((r): SearchResult[] =>
    typeof r.id === 'string'
      ? [
          {
            id: r.id,
            name: typeof r.name === 'string' ? r.name : 'Unnamed business',
            city: typeof r.city === 'string' ? r.city : null,
            country: typeof r.country === 'string' ? r.country : null,
            webDomain: typeof r.web_domain === 'string' ? r.web_domain : null,
            segmentId: typeof r.segment_id === 'string' ? r.segment_id : null,
            grade: typeof r.grade === 'string' ? r.grade : null,
            stage: typeof r.stage === 'string' ? r.stage : 'new',
            createdAt: typeof r.created_at === 'string' ? r.created_at : null,
          },
        ]
      : [],
  )
}

/* ------------------------------------------------------------------------------------------------------------
 * Insights: insights_summary(from_ts, to_ts, filters)
 * ---------------------------------------------------------------------------------------------------------- */

export type Counts = { leads: number; contacted: number; replied: number; meetings: number; proposals: number; won: number }
export type CountsRow = Counts & { id: string }
export type CostDay = { day: string; inr: number }

export type InsightsQuality = {
  leads: number
  phoneRate: number | null
  ownPhoneRate: number | null
  wrongRate: number | null
  medianSignalAgeDays: number | null
  thumbsUpRate: number | null
  votes: number
}

export type InsightsCosts = {
  days: CostDay[]
  /** The daily cap in rupees (750 when the setting is missing or not a positive number). */
  cap: number
  spend: number
  perResearched: number | null
  perGoodLead: number | null
  perWon: number | null
  researched: number
  goodLeads: number
  won: number
}

export type Insights = {
  total: Counts
  bySegment: CountsRow[]
  byGroup: CountsRow[]
  quality: InsightsQuality
  /** Admins only (null for everyone else). */
  costs: InsightsCosts | null
}

const toCounts = (v: unknown): Counts => {
  const c = obj(v)
  return {
    leads: count(c.leads),
    contacted: count(c.contacted),
    replied: count(c.replied),
    meetings: count(c.meetings),
    proposals: count(c.proposals),
    won: count(c.won),
  }
}
const ratio = (part: number, whole: number) => (whole ? part / whole : null)

/** The daily cap from settings (a JSON number or numeric string): 750 unless it is a positive number. */
export const capOf = (v: unknown) => {
  const n = Number(typeof v === 'string' || typeof v === 'number' ? v : NaN)
  return Number.isFinite(n) && n > 0 ? n : 750
}

export function toInsights(data: Json | null): Insights {
  const d = obj(data)
  const q = obj(d.quality)
  const leads = count(q.leads)
  const votes = count(q.votes)
  const costsJson = d.costs && typeof d.costs === 'object' ? obj(d.costs) : null
  let costs: InsightsCosts | null = null
  if (costsJson) {
    const days = list<Obj>(costsJson.days).map((x) => ({ day: String(x.day), inr: amount(x.inr) ?? 0 }))
    const spend = days.reduce((s, x) => s + x.inr, 0)
    const per = (n: number) => (n > 0 ? spend / n : null)
    const researched = count(costsJson.researched)
    const goodLeads = count(costsJson.good_leads)
    const won = count(costsJson.won)
    costs = { days, cap: capOf(costsJson.cap), spend, perResearched: per(researched), perGoodLead: per(goodLeads), perWon: per(won), researched, goodLeads, won }
  }
  return {
    total: toCounts(d.total),
    bySegment: list<Obj>(d.by_segment).map((r) => ({ id: String(r.id ?? 'unknown'), ...toCounts(r) })),
    byGroup: list<Obj>(d.by_group).map((r) => ({ id: String(r.id ?? 'unknown'), ...toCounts(r) })),
    quality: {
      leads,
      phoneRate: ratio(count(q.with_phone), leads),
      ownPhoneRate: ratio(count(q.own_phone), leads),
      wrongRate: ratio(count(q.wrong), count(q.contacted)),
      medianSignalAgeDays: amount(q.median_signal_age_days),
      thumbsUpRate: ratio(count(q.up_votes), votes),
      votes,
    },
    costs,
  }
}

/* ------------------------------------------------------------------------------------------------------------
 * Engine: engine_counts()
 * ---------------------------------------------------------------------------------------------------------- */

export type SourceHealthRow = {
  source: string
  enabled: boolean
  last_ok_at: string | null
  last_error_at: string | null
  last_error: string | null
  blocked_until: string | null
  requests_today: number
  health: string
}
export type RunRow = { id: string; kind: string; started_at: string; finished_at: string | null; status: string; stats: Json; error: string | null }
export type CustomQueryRow = { id: string; segment_id: string; query: string; status: string; created_at: string }

export type EngineLive = {
  researchedBy: Map<string, number>
  leadsBy: Map<string, number>
  spendToday: number
  sources: SourceHealthRow[]
  runs: RunRow[]
  queries: CustomQueryRow[]
}

const perSegment = (v: unknown) => new Map(Object.entries(obj(v)).map(([seg, n]) => [seg, count(n)]))

export function toEngineLive(data: Json | null): EngineLive {
  const d = obj(data)
  return {
    researchedBy: perSegment(d.researched_yesterday),
    leadsBy: perSegment(d.leads_yesterday),
    spendToday: amount(d.spend_today) ?? 0,
    sources: list<SourceHealthRow>(d.sources),
    runs: list<RunRow>(d.runs),
    queries: list<CustomQueryRow>(d.queries),
  }
}
