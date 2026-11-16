// Settings > Mailbox and Sending: the outreach mailbox (migration 0022, `mailboxes`) and the settings that steer
// sending (`outreach.*`), as the page shows them. Pure, so it is unit tested; the warm-up maths follow the engine
// (engine/src/nument_engine/outreach/mailbox.py: one daily cap per week since the first send, the last one holds).

export type MailboxStatus = 'disconnected' | 'warming' | 'active' | 'paused' | 'error'

export type Mailbox = {
  id: string
  email: string
  display_name: string
  status: MailboxStatus
  paused_reason: string | null
  warmup_started_on: string | null
  sent_today: number
  sent_day: string | null
  last_error: string | null
  connected_at: string | null
}

export type OutreachMode = 'off' | 'manual' | 'auto'

export type SendingSettings = {
  mode: OutreachMode
  paused: boolean
  /** Daily caps, one per warm-up week. */
  warmup: number[]
  /** Sending pauses on its own at this bounce rate (percent). */
  bouncePausePct: number | null
}

export const OUTREACH_KEYS = ['outreach.mode', 'outreach.paused', 'outreach.warmup', 'outreach.bounce_pause_pct'] as const

export const MODE_LABEL: Record<OutreachMode, string> = {
  off: 'Off',
  manual: 'You approve every email',
  auto: 'Good leads go out on their own',
}

const DEFAULT_WARMUP = [10, 15, 20, 25, 30, 35, 40]
const STATUSES: readonly MailboxStatus[] = ['disconnected', 'warming', 'active', 'paused', 'error']

/** The outreach settings from their rows; anything missing or malformed falls back to the engine's defaults. */
export function toSendingSettings(rows: readonly { key: string; value: unknown }[]): SendingSettings {
  const get = (key: string) => rows.find((r) => r.key === key)?.value
  const mode = get('outreach.mode')
  const warmup = get('outreach.warmup')
  const caps = Array.isArray(warmup) ? warmup.map(Number).filter((n) => Number.isFinite(n) && n >= 0).map(Math.floor) : []
  const pct = Number(get('outreach.bounce_pause_pct'))
  return {
    mode: mode === 'manual' || mode === 'auto' ? mode : 'off',
    paused: get('outreach.paused') === true || get('outreach.paused') === 'true',
    warmup: caps.length ? caps : DEFAULT_WARMUP,
    bouncePausePct: Number.isFinite(pct) && pct > 0 ? pct : null,
  }
}

/** A mailbox row from the database, or null when it is not one. */
export function toMailbox(v: unknown): Mailbox | null {
  if (!v || typeof v !== 'object') return null
  const r = v as Record<string, unknown>
  if (typeof r.id !== 'string' || typeof r.email !== 'string') return null
  const str = (k: string) => (typeof r[k] === 'string' && r[k] !== '' ? (r[k] as string) : null)
  return {
    id: r.id,
    email: r.email,
    display_name: str('display_name') ?? 'Nument',
    status: STATUSES.includes(r.status as MailboxStatus) ? (r.status as MailboxStatus) : 'disconnected',
    paused_reason: str('paused_reason'),
    warmup_started_on: str('warmup_started_on'),
    sent_today: Number(r.sent_today) || 0,
    sent_day: str('sent_day'),
    last_error: str('last_error'),
    connected_at: str('connected_at'),
  }
}

const DAY_MS = 86_400_000
const dayNumber = (day: string) => Math.floor(Date.parse(`${day}T00:00:00Z`) / DAY_MS)

export type Warmup = {
  /** Warm-up week, from 1 (0 before a future start). */
  week: number
  weeks: number
  capNow: number
  capEnd: number
  done: boolean
  started: boolean
  /** Sent today (India day), against today's cap. */
  sentToday: number
}

/** Where the mailbox is in its warm-up on the India day `today` (YYYY-MM-DD). */
export function warmupState(mailbox: Pick<Mailbox, 'warmup_started_on' | 'sent_today' | 'sent_day'>, schedule: readonly number[], today: string): Warmup {
  const caps = schedule.length ? schedule : DEFAULT_WARMUP
  const start = mailbox.warmup_started_on
  const week = !start ? 1 : dayNumber(today) < dayNumber(start) ? 0 : Math.floor((dayNumber(today) - dayNumber(start)) / 7) + 1
  return {
    week,
    weeks: caps.length,
    capNow: week === 0 ? 0 : (caps[Math.min(week, caps.length) - 1] ?? 0),
    capEnd: caps[caps.length - 1] ?? 0,
    done: Boolean(start) && week >= caps.length,
    started: Boolean(start),
    sentToday: mailbox.sent_day === today ? mailbox.sent_today : 0,
  }
}

export type Health = { tone: 'ok' | 'warn' | 'bad' | 'none'; label: string }

const PAUSE_REASON: Record<string, string> = {
  bounce_rate: 'too many emails bounced',
  auth: 'Gmail asked to sign in again',
  manual: 'paused by hand',
}

/** One calm line about the mailbox: a dot and a few words, with the bounce share when there are sends. */
export function mailboxHealth(mailbox: Mailbox | null, bounces: { bounced: number; sent: number }, paused: boolean): Health {
  if (!mailbox || mailbox.status === 'disconnected') return { tone: 'none', label: 'No mailbox connected' }
  if (mailbox.status === 'error') return { tone: 'bad', label: mailbox.last_error ? `Error · ${mailbox.last_error}` : 'Error' }
  const rate = bounces.sent ? `${((bounces.bounced * 100) / bounces.sent).toFixed(1).replace(/\.0$/, '')}% bounced of the last ${bounces.sent}` : 'Nothing sent yet'
  if (mailbox.status === 'paused') {
    const why = mailbox.paused_reason ? (PAUSE_REASON[mailbox.paused_reason] ?? mailbox.paused_reason) : ''
    return { tone: 'warn', label: `Paused${why ? `: ${why}` : ''} · ${rate}` }
  }
  if (paused) return { tone: 'warn', label: `Sending paused · ${rate}` }
  return { tone: 'ok', label: `Good · ${rate}` }
}

export const MAILBOX_STATUS_LABEL: Record<MailboxStatus, string> = {
  disconnected: 'Not connected',
  warming: 'Warming up',
  active: 'Connected',
  paused: 'Paused',
  error: 'Needs attention',
}

export const MAILBOX_STATUS_TONE: Record<MailboxStatus, Health['tone']> = {
  disconnected: 'none',
  warming: 'ok',
  active: 'ok',
  paused: 'warn',
  error: 'bad',
}
