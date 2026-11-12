// Leads list filters live in the URL, so every view is a shareable link (plan 15.6.4).
// One parser and one query builder serve the page, the CSV export and saved views.
import { GRADES, type Grade } from '@/lib/grades'
import { PITCH_VALUES, SIGNAL_VALUES, type PitchMode, type SignalType } from '@/lib/signals'
import { CLOSED_STAGE_LIST, STAGE_VALUES, type Stage } from '@/lib/stages'
import { istMidnightUtc, addDays } from '@/lib/dates'

export const PAGE_SIZE = 50

export const SORTS = {
  created: { column: 'created_at', label: 'Added' },
  score: { column: 'total', label: 'Score' },
  company: { column: 'name', label: 'Company' },
  grade: { column: 'grade', label: 'Grade' },
  stage: { column: 'stage', label: 'Stage' },
  activity: { column: 'last_activity_at', label: 'Last activity' },
  due: { column: 'due_at', label: 'Due' },
} as const
export type SortKey = keyof typeof SORTS

export type LeadFilters = {
  q: string
  seg: string[]
  country: string[]
  city: string[]
  grade: Grade[]
  signal: SignalType[]
  stage: Stage[]
  pitch: PitchMode[]
  mobile: boolean
  overdue: boolean
  owner: string
  from: string
  to: string
  sort: SortKey
  dir: 'asc' | 'desc'
  page: number
}

export const EMPTY_FILTERS: LeadFilters = {
  q: '',
  seg: [],
  country: [],
  city: [],
  grade: [],
  signal: [],
  stage: [],
  pitch: [],
  mobile: false,
  overdue: false,
  owner: '',
  from: '',
  to: '',
  sort: 'created',
  dir: 'desc',
  page: 1,
}

type ParamSource = URLSearchParams | Record<string, string | string[] | undefined>

function getAll(src: ParamSource, key: string): string[] {
  if (src instanceof URLSearchParams) return src.getAll(key)
  const v = src[key]
  return v === undefined ? [] : Array.isArray(v) ? v : [v]
}

const SLUG = /^[a-z0-9-]{1,40}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const DAY = /^\d{4}-\d{2}-\d{2}$/

const oneOf = <T extends string>(values: readonly T[], list: string[]) =>
  [...new Set(list.flatMap((v) => v.split(',')).filter((v): v is T => (values as readonly string[]).includes(v)))]

/** Strict parse: unknown keys and values are dropped, so the URL can never inject a filter. */
export function parseLeadFilters(src: ParamSource): LeadFilters {
  const first = (k: string) => getAll(src, k)[0] ?? ''
  const sort = first('sort')
  const page = Number.parseInt(first('page'), 10)
  const owner = first('owner')
  return {
    q: first('q').trim().slice(0, 80),
    seg: [...new Set(getAll(src, 'seg').flatMap((v) => v.split(',')).filter((v) => SLUG.test(v)))],
    country: [...new Set(getAll(src, 'country').flatMap((v) => v.split(',')).filter((v) => /^[a-z]{2}$/.test(v)))],
    city: [...new Set(getAll(src, 'city').map((v) => v.trim().slice(0, 60)).filter(Boolean))].slice(0, 20),
    grade: oneOf(GRADES, getAll(src, 'grade')),
    signal: oneOf(SIGNAL_VALUES, getAll(src, 'signal')),
    stage: oneOf(STAGE_VALUES, getAll(src, 'stage')),
    pitch: oneOf(PITCH_VALUES, getAll(src, 'pitch')),
    mobile: first('mobile') === '1',
    overdue: first('overdue') === '1',
    owner: owner === 'me' || owner === 'none' || UUID.test(owner) ? owner : '',
    from: DAY.test(first('from')) ? first('from') : '',
    to: DAY.test(first('to')) ? first('to') : '',
    sort: sort in SORTS ? (sort as SortKey) : 'created',
    dir: first('dir') === 'asc' ? 'asc' : 'desc',
    page: Number.isFinite(page) && page > 0 ? Math.min(page, 10_000) : 1,
  }
}

/** URL query for a filter set. Defaults are left out to keep links short. */
export function filtersToQuery(f: Partial<LeadFilters>, overrides: Partial<LeadFilters> = {}): string {
  const v = { ...EMPTY_FILTERS, ...f, ...overrides }
  const p = new URLSearchParams()
  if (v.q) p.set('q', v.q)
  for (const key of ['seg', 'country', 'city', 'grade', 'signal', 'stage', 'pitch'] as const) {
    for (const item of v[key]) p.append(key, item)
  }
  if (v.mobile) p.set('mobile', '1')
  if (v.overdue) p.set('overdue', '1')
  if (v.owner) p.set('owner', v.owner)
  if (v.from) p.set('from', v.from)
  if (v.to) p.set('to', v.to)
  if (v.sort !== 'created') p.set('sort', v.sort)
  if (v.dir !== 'desc') p.set('dir', v.dir)
  if (v.page > 1) p.set('page', String(v.page))
  return p.toString()
}

export const activeFilterCount = (f: LeadFilters) =>
  [f.seg, f.country, f.city, f.grade, f.signal, f.stage, f.pitch].filter((a) => a.length > 0).length +
  [f.mobile, f.overdue, Boolean(f.owner), Boolean(f.from || f.to), Boolean(f.q)].filter(Boolean).length

/** Characters that would break a PostgREST `or=(...)` filter are removed from free text. */
export const sanitizeSearch = (q: string) => q.replace(/[,()"'*%\\:]/g, ' ').replace(/\s+/g, ' ').trim()

// A structural view of the PostgREST filter builder, so one function can filter any leads query.
type FilterOps = {
  in(column: string, values: readonly string[]): FilterOps
  eq(column: string, value: string): FilterOps
  is(column: string, value: null): FilterOps
  gte(column: string, value: string): FilterOps
  lt(column: string, value: string): FilterOps
  or(filters: string): FilterOps
  not(column: string, operator: string, value: string): FilterOps
}

export type FilterContext = { userId: string; today: string }

/** Applies every filter in `f` to a query on v_leads_caller (or v_leads_admin, which has the same columns). */
export function applyLeadFilters<Q>(query: Q, f: LeadFilters, ctx: FilterContext): Q {
  let q = query as unknown as FilterOps
  if (f.seg.length) q = q.in('segment_id', f.seg)
  if (f.country.length) q = q.in('country', f.country)
  if (f.city.length) q = q.in('city', f.city)
  if (f.grade.length) q = q.in('grade', f.grade)
  if (f.stage.length) q = q.in('stage', f.stage)
  if (f.pitch.length) q = q.in('pitch_mode', f.pitch)
  if (f.signal.length) q = q.in('top_signal_type', f.signal)
  if (f.mobile) q = q.eq('phone_type', 'mobile')
  if (f.owner === 'me') q = q.eq('owner_id', ctx.userId)
  else if (f.owner === 'none') q = q.is('owner_id', null)
  else if (f.owner) q = q.eq('owner_id', f.owner)
  if (f.overdue) {
    q = q.lt('due_at', ctx.today).not('stage', 'in', CLOSED_STAGE_LIST)
  }
  if (f.from) q = q.gte('created_at', istMidnightUtc(f.from))
  if (f.to) q = q.lt('created_at', istMidnightUtc(addDays(f.to, 1)))
  const text = sanitizeSearch(f.q)
  if (text) {
    const parts = [`name.ilike.*${text}*`, `web_domain.ilike.*${text}*`]
    const digits = text.replace(/\D/g, '')
    if (digits.length >= 4) parts.push(`phone_e164.ilike.*${digits}*`)
    q = q.or(parts.join(','))
  }
  return q as unknown as Q
}
