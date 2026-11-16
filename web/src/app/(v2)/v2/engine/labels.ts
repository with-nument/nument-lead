// Plain words and status dots for the Engine page. Pure, so they are unit tested.

type Tone = 'ok' | 'warn' | 'bad' | 'none'

export const RUN_LABEL: Record<string, string> = {
  night: 'Night run',
  morning: 'Morning run',
  midday: 'Midday run',
  outreach: 'Email sending',
  backlog: 'Backlog',
  sheet_sync: 'Sheet sync',
  weekly: 'Weekly report',
  monthly: 'Monthly report',
  manual: 'Manual run',
}

const RUN_STATUS: Record<string, { tone: Tone; label: string }> = {
  ok: { tone: 'ok', label: 'Done' },
  running: { tone: 'none', label: 'Running' },
  partial: { tone: 'warn', label: 'Partly done' },
  failed: { tone: 'bad', label: 'Failed' },
}

export const runStatus = (status: string) => RUN_STATUS[status] ?? { tone: 'none' as Tone, label: status }

const SOURCE_HEALTH: Record<string, { tone: Tone; label: string }> = {
  ok: { tone: 'ok', label: 'Healthy' },
  stale: { tone: 'warn', label: 'Quiet lately' },
  error: { tone: 'bad', label: 'Failing' },
  blocked: { tone: 'bad', label: 'Blocked' },
  disabled: { tone: 'none', label: 'Off' },
}

export const sourceHealth = (health: string | null | undefined) => SOURCE_HEALTH[health ?? ''] ?? { tone: 'none' as Tone, label: 'Unknown' }

export const POST_STATUS: Record<string, string> = {
  new: 'Waiting for the night run',
  processing: 'Being researched',
  processed: 'Researched',
  researched: 'Researched',
  lead_created: 'Lead created',
  rejected: 'Not a fit',
}

export const QUERY_STATUS: Record<string, string> = { new: 'Tonight', running: 'Running', done: 'Done', failed: 'Failed' }

/** "3 min", "1 h 5 min", or empty while the run is going. */
export function runDuration(start: string, end: string | null) {
  if (!end) return ''
  const mins = Math.round((Date.parse(end) - Date.parse(start)) / 60_000)
  return mins < 1 ? 'under a minute' : mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`
}

/** What a run did, from its stats: "120 researched · 14 leads · ₹82". Money only when `money` is true. */
export function runResult(stats: unknown, money: (n: number) => string) {
  if (!stats || typeof stats !== 'object' || Array.isArray(stats)) return ''
  const s = stats as Record<string, unknown>
  const num = (k: string) => (typeof s[k] === 'number' ? (s[k] as number) : null)
  const parts: string[] = []
  const researched = num('researched')
  const leads = num('leads') ?? num('leads_created')
  const sent = num('sent')
  const cost = num('cost_inr') ?? num('inr')
  if (researched !== null) parts.push(`${researched.toLocaleString('en-IN')} researched`)
  if (leads !== null) parts.push(`${leads.toLocaleString('en-IN')} ${leads === 1 ? 'lead' : 'leads'}`)
  if (sent !== null) parts.push(`${sent.toLocaleString('en-IN')} sent`)
  if (cost !== null) parts.push(money(cost))
  return parts.join(' · ')
}
