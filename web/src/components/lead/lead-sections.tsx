import { ExternalLink } from 'lucide-react'
import { Tag } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import type { Json } from '@/lib/database.types'
import { formatDate, formatDateTime, relativeAge } from '@/lib/dates'
import { hostOf } from '@/lib/format'
import { lostReasonLabel } from '@/lib/outcomes'
import { pitchLabel, signalLabel } from '@/lib/signals'
import { stageOf } from '@/lib/stages'

/* ---------- Why this lead ---------- */

type Score = { fit: number; can_pay: number; intent: number; reach: number; total: number; grade: string; reasons: Json; judge_note: string | null; judge_model: string | null }

function Bar({ label, value, max, display }: { label: string; value: number; max: number; display: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)_64px] items-center gap-3">
      <span className="text-sm text-tx-2">{label}</span>
      <div className="h-1.5 rounded-full bg-surface-3" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
        <div className="h-full rounded-full bg-indigo-600" style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular text-right text-sm text-tx-3">{display}</span>
    </div>
  )
}

/** Reads scores.reasons, which is {fit: [...], can_pay: [...], intent: [{type, value}], reach: [...]} (Step 11). */
function reasonLines(reasons: Json): string[] {
  const out: string[] = []
  const push = (v: Json | undefined) => {
    if (typeof v === 'string' && v.trim()) out.push(v.trim())
    else if (Array.isArray(v)) v.forEach((x) => push(x))
    else if (v && typeof v === 'object' && !Array.isArray(v)) {
      const o = v as Record<string, Json | undefined>
      if (typeof o.type === 'string') out.push(`${signalLabel(o.type)}${typeof o.value === 'number' ? ` (+${o.value})` : ''}`)
      else if (typeof o.text === 'string') out.push(o.text)
    }
  }
  if (Array.isArray(reasons)) push(reasons)
  else if (reasons && typeof reasons === 'object') {
    const r = reasons as Record<string, Json | undefined>
    for (const key of ['intent', 'fit', 'can_pay', 'reach']) push(r[key])
  }
  return [...new Set(out)].slice(0, 12)
}

/** The four parts of the total (score s2.0): need, can pay, fit and reach add up to the number shown.
 * Older s1.0 rows carry no `parts`, so they are converted with the s2.0 weights for display. */
export function scoreParts(score: Score): { label: string; value: number; max: number }[] {
  const reasons = (score.reasons && typeof score.reasons === 'object' && !Array.isArray(score.reasons) ? score.reasons : {}) as Record<string, Json | undefined>
  const parts = (reasons.parts && typeof reasons.parts === 'object' && !Array.isArray(reasons.parts) ? reasons.parts : {}) as Record<string, Json | undefined>
  const num = (v: Json | undefined, fallback: number) => (typeof v === 'number' ? v : fallback)
  const fitPoints = score.fit >= 3 ? 10 : score.fit === 2 ? 6 : 0
  return [
    { label: 'Need', value: Math.min(35, num(parts.need, Number(score.intent))), max: 35 },
    { label: 'Can pay', value: num(parts.can_pay, (Number(score.can_pay) / 30) * 35), max: 35 },
    { label: 'Fit', value: num(parts.fit, fitPoints), max: 10 },
    { label: 'Reach', value: num(parts.reach, Number(score.reach) * 20), max: 20 },
  ]
}

export function WhyCard({ score, pitchMode, testGroup, judgeNote }: { score: Score | null; pitchMode: string | null; testGroup: string | null; judgeNote: string | null }) {
  const lines = score ? reasonLines(score.reasons) : []
  const note = score?.judge_note ?? judgeNote
  return (
    <Card aria-labelledby="why-title" data-tour="lead-why">
      <CardHeader id="why-title" title="Why this lead" />
      <CardBody className="flex flex-col gap-5">
        {score ? (
          <div className="flex flex-col gap-2.5">
            {scoreParts(score).map((p) => (
              <Bar key={p.label} label={p.label} value={p.value} max={p.max} display={`${Math.round(p.value)} / ${p.max}`} />
            ))}
          </div>
        ) : (
          <p className="text-base text-tx-3">No score yet.</p>
        )}
        {lines.length ? (
          <ul className="flex flex-col gap-1.5 text-base text-tx-2">
            {lines.map((l) => (
              <li key={l} className="flex gap-2">
                <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-indigo-400" />
                {l}
              </li>
            ))}
          </ul>
        ) : null}
        {note ? (
          <figure className="border-l-2 border-indigo-200 pl-3">
            <blockquote className="text-base text-tx-2 italic">{note}</blockquote>
            {score?.judge_model ? <figcaption className="label-mono mt-1">{score.judge_model}</figcaption> : null}
          </figure>
        ) : null}
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {pitchMode ? <span className="label-mono">Pitch: {pitchLabel(pitchMode)}</span> : null}
          {testGroup ? <span className="label-mono break-all">Test group: {testGroup}</span> : null}
        </div>
      </CardBody>
    </Card>
  )
}

/* ---------- Signals ---------- */

export function SignalsCard({ signals, now }: { signals: { id: string; type: string; points: number; observed_at: string; expires_at: string; url: string | null; quote: string | null; source: string }[]; now: Date }) {
  return (
    <Card aria-labelledby="signals-title">
      <CardHeader id="signals-title" title="Signals" description="Dated evidence of need, newest first." />
      <CardBody>
        {signals.length ? (
          <ul className="flex flex-col divide-y divide-line-2">
            {signals.map((s) => {
              const expired = Date.parse(s.expires_at) <= now.getTime()
              return (
                <li key={s.id} className={cn('py-3 first:pt-0 last:pb-0', expired && 'opacity-55')}>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-base font-medium text-tx-1">{signalLabel(s.type)}</span>
                    <span className="text-sm text-tx-3">{relativeAge(s.observed_at, now)}</span>
                    <Tag>{`+${Math.round(Number(s.points))}`}</Tag>
                    {expired ? <Tag>expired</Tag> : null}
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-sm text-indigo-800 hover:text-indigo-900">
                        {hostOf(s.url) || 'Evidence'}
                        <ExternalLink aria-hidden className="size-3.5" />
                      </a>
                    ) : null}
                  </div>
                  {s.quote ? <p className="mt-1 text-sm text-tx-3">&ldquo;{s.quote}&rdquo;</p> : null}
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-base text-tx-3">No signals recorded for this business.</p>
        )}
      </CardBody>
    </Card>
  )
}

/* ---------- Facts ---------- */

const FACT_GROUPS: { title: string; fields: string[] }[] = [
  { title: 'Team', fields: ['decision_maker', 'staff_or_doctors', 'jsonld_employees', 'in_house_tech'] },
  { title: 'Branches', fields: ['branches', 'locations_url'] },
  { title: 'Services', fields: ['service', 'price_point', 'jsonld_price_range', 'language'] },
  { title: 'Booking', fields: ['booking_method', 'whatsapp_present', 'chat_widget', 'contact_form_url'] },
  { title: 'Tech', fields: ['tech_stack', 'site_speed_mobile', 'website_status', 'is_agency_or_vendor'] },
  { title: 'Careers', fields: ['careers_role', 'careers_url', 'jsonld_job'] },
]
const FIELD_LABEL: Record<string, string> = {
  decision_maker: 'Decision maker',
  staff_or_doctors: 'Staff or doctors',
  jsonld_employees: 'Employees',
  in_house_tech: 'In-house tech team',
  branches: 'Branches',
  locations_url: 'Locations page',
  service: 'Service',
  price_point: 'Price point',
  jsonld_price_range: 'Price range',
  language: 'Language',
  booking_method: 'Booking',
  whatsapp_present: 'WhatsApp on site',
  chat_widget: 'Chat widget',
  contact_form_url: 'Contact form',
  tech_stack: 'Tech stack',
  site_speed_mobile: 'Mobile speed',
  website_status: 'Website status',
  is_agency_or_vendor: 'Agency or vendor',
  careers_role: 'Hiring for',
  careers_url: 'Careers page',
  jsonld_job: 'Job post',
  business_name: 'Business name',
  phone: 'Phone',
  email: 'Email',
  sales_note: 'Sales note',
}
export const fieldLabel = (f: string) => FIELD_LABEL[f] ?? f.replace(/^jsonld_/, '').replaceAll('_', ' ').replace(/^\w/, (c) => c.toUpperCase())

/** A fact value (jsonb) as short readable text. */
export function factText(v: Json): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number' || typeof v === 'string') return String(v)
  if (Array.isArray(v)) return v.map(factText).filter(Boolean).join(', ')
  const o = v as Record<string, Json | undefined>
  for (const key of ['value', 'name', 'text', 'label']) if (o[key] !== undefined) return factText(o[key] as Json)
  return Object.entries(o)
    .filter(([, x]) => x !== null && x !== undefined && typeof x !== 'object')
    .map(([k, x]) => `${k.replaceAll('_', ' ')}: ${String(x)}`)
    .join(', ')
}

type Fact = { id: string; field: string; value: Json; quote: string | null; url: string | null; verified: boolean; created_at: string }

export function FactsCard({ facts, toggle }: { facts: Fact[]; toggle?: React.ReactNode }) {
  // Latest fact per field.
  const latest = new Map<string, Fact>()
  for (const f of facts) if (!latest.has(f.field)) latest.set(f.field, f)
  const used = new Set<string>()
  const groups = FACT_GROUPS.map((g) => ({
    title: g.title,
    items: g.fields.flatMap((field) => {
      const f = latest.get(field)
      if (!f) return []
      used.add(field)
      return [f]
    }),
  }))
  const other = [...latest.values()].filter((f) => !used.has(f.field) && !f.field.startsWith('jsonld_phone') && !f.field.startsWith('jsonld_email'))
  if (other.length) groups.push({ title: 'Other', items: other })
  const shown = groups.filter((g) => g.items.length)
  return (
    <Card aria-labelledby="facts-title">
      <CardHeader id="facts-title" title="Facts" description="Each fact has the quote and the page it came from." actions={toggle} />
      <CardBody>
        {shown.length ? (
          <div className="flex flex-col gap-5">
            {shown.map((g) => (
              <section key={g.title}>
                <h3 className="mb-2 text-sm font-medium text-tx-2">{g.title}</h3>
                <dl className="flex flex-col divide-y divide-line-2 rounded-xl border border-line-2">
                  {g.items.map((f) => (
                    <div key={f.id} className="grid gap-1 px-3.5 py-2.5 sm:grid-cols-[150px_minmax(0,1fr)] sm:gap-4">
                      <dt className="text-sm text-tx-3">{fieldLabel(f.field)}</dt>
                      <dd className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2 text-base text-tx-1">
                          <span className="break-words">{factText(f.value) || 'Not stated'}</span>
                          {!f.verified ? <Tag tone="warn">unverified</Tag> : null}
                        </div>
                        {f.quote ? <p className="mt-0.5 text-sm text-tx-3">&ldquo;{f.quote}&rdquo;</p> : null}
                        {f.url ? (
                          <a href={f.url} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-xs text-indigo-800 hover:text-indigo-900">
                            {hostOf(f.url)}
                            <ExternalLink aria-hidden className="size-3" />
                          </a>
                        ) : null}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        ) : (
          <p className="text-base text-tx-3">No verified facts yet.</p>
        )}
      </CardBody>
    </Card>
  )
}

/* ---------- Website and tech check ---------- */

export function TechCard({ facts }: { facts: Fact[] }) {
  const latest = new Map<string, Fact>()
  for (const f of facts) if (!latest.has(f.field)) latest.set(f.field, f)
  const yesNo = (field: string) => {
    const f = latest.get(field)
    if (!f) return null
    const v = f.value
    if (typeof v === 'boolean') return v
    const s = factText(v).toLowerCase()
    return s === 'yes' || s === 'true' ? true : s === 'no' || s === 'false' ? false : null
  }
  const stack = latest.get('tech_stack')?.value
  const stackText = stack ? factText(stack) : ''
  const has = (needle: RegExp) => (stackText ? needle.test(stackText) : null)
  const speed = latest.get('site_speed_mobile')?.value
  const speedNum = typeof speed === 'number' ? speed : Number.parseFloat(factText(speed ?? null))
  const booking = latest.get('booking_method')
  const rows: { label: string; value: boolean | null; text?: string }[] = [
    { label: 'Online booking', value: booking ? !/none|no|phone only/i.test(factText(booking.value)) : null, text: booking ? factText(booking.value) : undefined },
    { label: 'WhatsApp button', value: yesNo('whatsapp_present') },
    { label: 'Chat widget', value: yesNo('chat_widget') },
    { label: 'Meta pixel', value: has(/meta|facebook/i) },
    { label: 'Google ads tag', value: has(/google ads|gtag|adwords|googleads/i) },
  ]
  const cms = stackText.match(/wordpress|wix|shopify|squarespace|webflow|joomla|drupal|next\.js|react/i)?.[0]
  const any = rows.some((r) => r.value !== null) || cms || Number.isFinite(speedNum)
  return (
    <Card aria-labelledby="tech-title">
      <CardHeader id="tech-title" title="Website and tech check" />
      <CardBody>
        {any ? (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            {rows.map((r) => (
              <div key={r.label} className="flex items-center justify-between gap-3 border-b border-line-2 py-1.5">
                <dt className="text-base text-tx-2">{r.label}</dt>
                <dd className="text-sm">
                  {r.value === null ? <span className="text-tx-3">Unknown</span> : r.value ? <Tag tone="ok">Yes</Tag> : <Tag>No</Tag>}
                </dd>
              </div>
            ))}
            <div className="flex items-center justify-between gap-3 border-b border-line-2 py-1.5">
              <dt className="text-base text-tx-2">Site built with</dt>
              <dd className="text-sm text-tx-2">{cms ?? <span className="text-tx-3">Unknown</span>}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-line-2 py-1.5">
              <dt className="text-base text-tx-2">Mobile speed</dt>
              <dd className="text-sm">
                {Number.isFinite(speedNum) ? <Tag tone={speedNum < 40 ? 'bad' : speedNum < 70 ? 'warn' : 'ok'}>{Math.round(speedNum)} / 100</Tag> : <span className="text-tx-3">Unknown</span>}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-base text-tx-3">The website has not been checked yet.</p>
        )}
      </CardBody>
    </Card>
  )
}

/* ---------- Timeline ---------- */

type Activity = { id: string; type: string; source: string; at: string; user_id: string | null; payload: Json }

function sentence(a: Activity, who: string): string {
  const p = (a.payload && typeof a.payload === 'object' && !Array.isArray(a.payload) ? a.payload : {}) as Record<string, Json | undefined>
  const str = (k: string) => (typeof p[k] === 'string' ? (p[k] as string) : '')
  switch (a.type) {
    case 'lead_created':
      return `Lead created${str('grade') ? `, grade ${str('grade')}` : ''}${str('pitch_mode') ? `, ${pitchLabel(str('pitch_mode')).toLowerCase()}` : ''}`
    case 'stage_change':
      return `${who} moved the stage from ${stageOf(str('from')).label} to ${stageOf(str('to')).label}`
    case 'grade_change':
      return `Grade changed from ${str('from') || 'none'} to ${str('to')}`
    case 'message_edited':
      return `${who} edited the message`
    case 'message_flagged':
      return 'The message checker asked for a human edit'
    case 'regen_request':
      return `${who} asked for a new message`
    case 'sent': {
      const ch = str('channel')
      const how = ch === 'web' ? ' on WhatsApp Web' : ch === 'app' ? ' on the WhatsApp app' : ch === 'call' ? ' by phone' : ch === 'email' ? ' by email' : ''
      return `${who} sent the first message${how}`
    }
    case 'followup_sent':
      return `${who} sent the day ${str('which') === 'd7' ? '7' : '3'} follow-up`
    case 'reply':
      return 'They replied'
    case 'call':
      return `${who} logged a call`
    case 'meeting':
      return `${who} logged a meeting`
    case 'proposal':
      return `${who} sent a proposal`
    case 'proposal_upload':
      return `${who} uploaded a proposal${str('file') ? ` (${str('file')})` : ''}`
    case 'note':
      return `${who} added a note`
    case 'edit': {
      const field = str('field')
      if (field === 'lost_reason') return `${who} gave the reason: ${(lostReasonLabel(str('reason')) ?? 'other').toLowerCase()}`
      const label = field === 'next_step' ? 'the next step' : field === 'owner' ? 'the owner' : field === 'deal_value' ? 'the deal value' : field.startsWith('followup') ? 'a follow-up message' : 'the lead'
      return `${who} changed ${label}`
    }
    case 'feedback':
      return `${who} rated the lead ${Number(p.rating) > 0 ? 'good' : 'not good'}${str('reason') ? ` (${str('reason').toLowerCase()})` : ''}`
    case 'skip':
      return `${who} skipped the lead for 7 days`
    case 'wrong_contact':
      return `${who} marked the number as wrong`
    case 'undo':
      return `${who} undid the last change`
    case 'merge':
      return 'Merged with a duplicate'
    case 'won':
      return 'Marked as won'
    case 'conflict_overridden':
      return 'The sheet and the app disagreed; the latest edit won'
    case 'unknown_stage':
      return 'The sheet had a stage the app does not know'
    default:
      return `${who} ${a.type.replaceAll('_', ' ')}`
  }
}

export function Timeline({ activities, names, now }: { activities: Activity[]; names: Map<string, string>; now: Date }) {
  return (
    <Card aria-labelledby="timeline-title" data-tour="lead-timeline">
      <CardHeader id="timeline-title" title="Timeline" description="Every change, from the app, the sheet and the engine." />
      <CardBody>
        {activities.length ? (
          <ol className="relative flex flex-col gap-4 border-l border-line pl-4">
            {activities.map((a) => {
              const who = a.user_id ? (names.get(a.user_id) ?? 'A teammate') : a.source === 'engine' ? 'The engine' : a.source === 'sheet' ? 'The sheet' : 'Someone'
              const p = (a.payload && typeof a.payload === 'object' && !Array.isArray(a.payload) ? a.payload : {}) as Record<string, Json | undefined>
              return (
                <li key={a.id} className="relative">
                  <span aria-hidden className="absolute top-1.5 -left-[21px] size-2.5 rounded-full border-2 border-surface bg-indigo-400" />
                  <div className="text-base text-tx-1">{sentence(a, who)}</div>
                  {a.type === 'note' && typeof p.text === 'string' ? <p className="mt-1 rounded-lg bg-surface-2 px-3 py-2 text-sm whitespace-pre-line text-tx-2">{p.text}</p> : null}
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-tx-3">
                    <time dateTime={a.at} title={formatDateTime(a.at)}>
                      {formatDateTime(a.at)}
                    </time>
                    <span aria-hidden>·</span>
                    <span>{relativeAge(a.at, now)}</span>
                    <Tag className="h-5 px-1.5 text-micro">{a.source}</Tag>
                  </div>
                </li>
              )
            })}
          </ol>
        ) : (
          <p className="text-base text-tx-3">Nothing has happened on this lead yet.</p>
        )}
      </CardBody>
    </Card>
  )
}

/* ---------- Pages read ---------- */

export function PagesCard({ pages, now }: { pages: { id: string; url: string; title: string | null; fetched_at: string }[]; now: Date }) {
  if (!pages.length) return null
  return (
    <Card aria-labelledby="pages-title">
      <CardHeader id="pages-title" title="Pages read" />
      <CardBody>
        <ul className="flex flex-col gap-2">
          {pages.map((p) => (
            <li key={p.id} className="min-w-0">
              <a href={p.url} target="_blank" rel="noopener noreferrer" className="block truncate text-base text-indigo-800 hover:text-indigo-900">
                {p.title || hostOf(p.url)}
              </a>
              <div className="text-xs text-tx-3">
                {hostOf(p.url)} · read {formatDate(p.fetched_at, now)}
              </div>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}
