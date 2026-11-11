// Every timestamp is stored in UTC and shown in India time (Asia/Kolkata), as the plan requires.
export const TIME_ZONE = 'Asia/Kolkata'
const IST_OFFSET_MINUTES = 330 // India has no daylight saving.
const DAY_MS = 86_400_000

type DateInput = string | number | Date

const toDate = (v: DateInput) => (v instanceof Date ? v : new Date(typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? `${v}T00:00:00+05:30` : v))
const clean = (s: string) => s.replace(/\u202f|\u00a0/g, ' ')

function parts(v: DateInput, options: Intl.DateTimeFormatOptions) {
  const out: Record<string, string> = {}
  for (const p of new Intl.DateTimeFormat('en-IN', { timeZone: TIME_ZONE, ...options }).formatToParts(toDate(v))) {
    out[p.type] = clean(p.value)
  }
  return out
}

/** "12 Nov, 4:30 pm" */
export function formatDateTime(v: DateInput) {
  const p = parts(v, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true })
  return `${p.day} ${p.month}, ${p.hour}:${p.minute} ${p.dayPeriod?.toLowerCase()}`
}

/** "12 Nov", or "12 Nov 2025" when the year is not the current one. */
export function formatDate(v: DateInput, now: Date = new Date()) {
  const p = parts(v, { day: 'numeric', month: 'short', year: 'numeric' })
  const thisYear = parts(now, { year: 'numeric' }).year
  return p.year === thisYear ? `${p.day} ${p.month}` : `${p.day} ${p.month} ${p.year}`
}

/** "Thu 12 Nov" */
export function formatWeekday(v: DateInput) {
  const p = parts(v, { weekday: 'short', day: 'numeric', month: 'short' })
  return `${p.weekday} ${p.day} ${p.month}`
}

/** "4:30 pm" */
export function formatTime(v: DateInput) {
  const p = parts(v, { hour: 'numeric', minute: '2-digit', hour12: true })
  return `${p.hour}:${p.minute} ${p.dayPeriod?.toLowerCase()}`
}

/** India date of an instant, as "YYYY-MM-DD" (what the database stores in date columns). */
export function istDate(v: DateInput = new Date()) {
  const p = parts(v, { year: 'numeric', month: '2-digit', day: '2-digit' })
  return `${p.year}-${p.month}-${p.day}`
}

/** Midnight India time of the given "YYYY-MM-DD", as a UTC ISO string. */
export function istMidnightUtc(day: string) {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(Date.UTC(y!, m! - 1, d!) - IST_OFFSET_MINUTES * 60_000).toISOString()
}

/** Add whole days to a "YYYY-MM-DD" date. */
export function addDays(day: string, days: number) {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(Date.UTC(y!, m! - 1, d! + days)).toISOString().slice(0, 10)
}

/** Monday 00:00 India time of the week containing `now`, as a UTC ISO string. */
export function startOfWeekIst(now: Date = new Date()) {
  const today = istDate(now)
  const [y, m, d] = today.split('-').map(Number)
  const weekday = new Date(Date.UTC(y!, m! - 1, d!)).getUTCDay() // 0 Sunday
  const back = (weekday + 6) % 7
  return istMidnightUtc(addDays(today, -back))
}

/** The 1st of this month, 00:00 India time, as a UTC ISO string. */
export function startOfMonthIst(now: Date = new Date()) {
  return istMidnightUtc(`${istDate(now).slice(0, 7)}-01`)
}

/** Whole days from `from` to `to` (both "YYYY-MM-DD"). */
export function daysBetween(from: string, to: string) {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS)
}

/** "just now", "3 hours ago", "4 days ago", "2 months ago". */
export function relativeAge(v: DateInput, now: Date = new Date()) {
  const diff = now.getTime() - toDate(v).getTime()
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  const abs = Math.abs(diff)
  const sign = diff >= 0 ? -1 : 1
  if (abs < 60_000) return 'just now'
  if (abs < 3_600_000) return rtf.format(sign * Math.round(abs / 60_000), 'minute')
  if (abs < DAY_MS) return rtf.format(sign * Math.round(abs / 3_600_000), 'hour')
  if (abs < 30 * DAY_MS) return rtf.format(sign * Math.round(abs / DAY_MS), 'day')
  if (abs < 365 * DAY_MS) return rtf.format(sign * Math.round(abs / (30 * DAY_MS)), 'month')
  return rtf.format(sign * Math.round(abs / (365 * DAY_MS)), 'year')
}

/** Due-date status of a "YYYY-MM-DD" date against today in India. */
export function dueState(due: string | null | undefined, today: string): 'none' | 'overdue' | 'today' | 'later' {
  if (!due) return 'none'
  const d = daysBetween(today, due)
  return d < 0 ? 'overdue' : d === 0 ? 'today' : 'later'
}
