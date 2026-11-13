import type { Metadata } from 'next'
import { Suspense } from 'react'
import { BudgetForm, CustomQueryForm, QuotaInput, RunNow, SegmentToggle, SourceToggle } from '@/components/engine/engine-controls'
import { SpendMeter } from '@/components/engine/meter'
import { Tag, type Tone } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import { ENGINE_DESCRIPTION, ENGINE_TITLE, EngineBody } from '@/components/skeletons'
import { early, requireRole } from '@/lib/auth'
import { formatDateTime, relativeAge } from '@/lib/dates'
import { formatInr, formatNumber } from '@/lib/format'
import { isDispatchConfigured } from '@/lib/github'
import { getEngineLive, getEngineOverview } from '@/lib/queries/engine'
import { cn } from '@/lib/cn'

export const metadata: Metadata = { title: 'Engine' }

const HEALTH_TONE: Record<string, Tone> = { ok: 'ok', stale: 'warn', error: 'bad', blocked: 'bad', disabled: 'neutral' }
const RUN_TONE: Record<string, Tone> = { ok: 'ok', running: 'indigo', partial: 'warn', failed: 'bad' }
const QUERY_TONE: Record<string, Tone> = { new: 'neutral', running: 'indigo', done: 'ok', failed: 'bad' }
const RUN_LABEL: Record<string, string> = { night: 'Night', morning: 'Morning', midday: 'Midday', sheet_sync: 'Sheet sync', weekly: 'Weekly', monthly: 'Monthly', manual: 'Manual' }

const th = 'label-mono h-10 border-b border-line-2 px-3 font-normal whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5'
const td = 'h-11 px-3 align-middle first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5'

export default function EnginePage() {
  return (
    <>
      <PageHeader title={ENGINE_TITLE} description={ENGINE_DESCRIPTION} />
      <Suspense fallback={<EngineBody />}>
        <Engine />
      </Suspense>
    </>
  )
}

function statsLine(stats: unknown) {
  if (!stats || typeof stats !== 'object' || Array.isArray(stats)) return ''
  const s = stats as Record<string, unknown>
  const num = (k: string) => (typeof s[k] === 'number' ? (s[k] as number) : null)
  const parts: string[] = []
  const researched = num('researched')
  const leads = num('leads') ?? num('leads_created')
  const cost = num('cost_inr') ?? num('inr')
  if (researched !== null) parts.push(`${formatNumber(researched)} researched`)
  if (leads !== null) parts.push(`${formatNumber(leads)} leads`)
  if (cost !== null) parts.push(formatInr(cost))
  return parts.join(' · ')
}

function duration(start: string, end: string | null) {
  if (!end) return ''
  const mins = Math.round((Date.parse(end) - Date.parse(start)) / 60_000)
  return mins < 1 ? 'under a minute' : mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`
}

async function Engine() {
  // The live reads run as the user (RLS: admin only) and start while the role is checked.
  const live = early(getEngineLive())
  await requireRole(['admin'])
  const data = await getEngineOverview(live)
  const now = new Date()
  const segments = data.segments

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card aria-labelledby="budget-title" data-tour="engine-budget">
          <CardHeader id="budget-title" title="Budget" />
          <CardBody className="flex flex-col gap-5">
            <SpendMeter spend={data.spendToday} cap={data.budget.daily_cap_inr} alertPct={data.budget.alert_pct} />
            <BudgetForm budget={data.budget} />
          </CardBody>
        </Card>
        <Card aria-labelledby="run-title">
          <CardHeader id="run-title" title="Run now" description="Starts the engine on GitHub Actions. Use a dry run to check before a real one." />
          <CardBody>
            <RunNow segments={segments.map((s) => ({ id: s.id, label: s.label }))} configured={isDispatchConfigured()} />
          </CardBody>
        </Card>
      </div>

      <Card aria-labelledby="segments-title">
        <CardHeader id="segments-title" title="Segments" description="Daily quota is how many businesses the engine researches per day in that segment." />
        <div className="relative mt-3 overflow-x-auto border-t border-line-2">
          <table className="w-full text-left text-base">
            <thead>
              <tr>
                <th scope="col" className={th}>Segment</th>
                <th scope="col" className={th}>On</th>
                <th scope="col" className={cn(th, 'text-right')}>Daily quota</th>
                <th scope="col" className={cn(th, 'text-right')}>Researched yesterday</th>
                <th scope="col" className={cn(th, 'text-right')}>Leads yesterday</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((s) => (
                <tr key={s.id} className="border-b border-line-2 last:border-b-0">
                  <td className={td}>
                    <div className="text-tx-1">{s.label}</div>
                    <div className="label-mono">{s.id}</div>
                  </td>
                  <td className={td}>
                    <SegmentToggle id={s.id} label={s.label} enabled={s.enabled} />
                  </td>
                  <td className={cn(td, 'text-right')}>
                    <div className="flex justify-end">
                      <QuotaInput id={s.id} label={s.label} quota={s.daily_quota} />
                    </div>
                  </td>
                  <td className={cn(td, 'text-right tabular text-tx-2')}>{formatNumber(s.researchedYesterday)}</td>
                  <td className={cn(td, 'text-right tabular text-tx-2')}>{formatNumber(s.leadsYesterday)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card aria-labelledby="sources-title" data-tour="engine-sources">
        <CardHeader id="sources-title" title="Sources" description="Turn a source off to stop the engine using it at once (kill switch)." />
        <div className="relative mt-3 overflow-x-auto border-t border-line-2">
          {data.sources.length ? (
            <table className="w-full text-left text-base">
              <thead>
                <tr>
                  <th scope="col" className={th}>Source</th>
                  <th scope="col" className={th}>Health</th>
                  <th scope="col" className={th}>On</th>
                  <th scope="col" className={th}>Last success</th>
                  <th scope="col" className={th}>Last error</th>
                  <th scope="col" className={cn(th, 'text-right')}>Requests today</th>
                </tr>
              </thead>
              <tbody>
                {data.sources.map((s) => (
                  <tr key={s.source} className={cn('border-b border-line-2 last:border-b-0', (s.health === 'error' || s.health === 'blocked') && 'bg-red-50/40')}>
                    <td className={cn(td, 'font-mono text-sm text-tx-1')}>{s.source}</td>
                    <td className={td}>
                      <Tag tone={HEALTH_TONE[s.health ?? ''] ?? 'neutral'}>{s.health ?? 'unknown'}</Tag>
                    </td>
                    <td className={td}>{s.source ? <SourceToggle source={s.source} enabled={Boolean(s.enabled)} /> : null}</td>
                    <td className={cn(td, 'whitespace-nowrap text-tx-3')}>{s.last_ok_at ? relativeAge(s.last_ok_at, now) : 'Never'}</td>
                    <td className={cn(td, 'max-w-[320px] text-sm')}>
                      {s.last_error ? (
                        <div className={cn('truncate', s.health === 'error' || s.health === 'blocked' ? 'text-bad' : 'text-tx-3')} title={s.last_error}>
                          {s.last_error}
                        </div>
                      ) : (
                        <span className="text-tx-3">None</span>
                      )}
                      {s.blocked_until && Date.parse(s.blocked_until) > now.getTime() ? <div className="text-xs text-bad">Blocked until {formatDateTime(s.blocked_until)}</div> : null}
                    </td>
                    <td className={cn(td, 'text-right tabular text-tx-2')}>{formatNumber(s.requests_today ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState text="No sources registered yet." />
          )}
        </div>
      </Card>

      <Card aria-labelledby="runs-title">
        <CardHeader id="runs-title" title="Runs" description="The last 20 runs, newest first." />
        <div className="relative mt-3 overflow-x-auto border-t border-line-2">
          {data.runs.length ? (
            <table className="w-full text-left text-base">
              <thead>
                <tr>
                  <th scope="col" className={th}>Run</th>
                  <th scope="col" className={th}>Started</th>
                  <th scope="col" className={th}>Took</th>
                  <th scope="col" className={th}>Status</th>
                  <th scope="col" className={th}>Result</th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.id} className="border-b border-line-2 last:border-b-0">
                    <td className={cn(td, 'text-tx-1')}>{RUN_LABEL[r.kind] ?? r.kind}</td>
                    <td className={cn(td, 'whitespace-nowrap text-tx-2')}>{formatDateTime(r.started_at)}</td>
                    <td className={cn(td, 'whitespace-nowrap text-tx-3')}>{duration(r.started_at, r.finished_at)}</td>
                    <td className={td}>
                      <Tag tone={RUN_TONE[r.status] ?? 'neutral'}>{r.status}</Tag>
                    </td>
                    <td className={cn(td, 'max-w-[380px] text-sm')}>
                      {r.error ? (
                        <div className="truncate text-bad" title={r.error}>
                          {r.error}
                        </div>
                      ) : (
                        <span className="text-tx-2">{statsLine(r.stats)}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState text="No runs yet. The first night run will show here." />
          )}
        </div>
      </Card>

      <Card aria-labelledby="queries-title">
        <CardHeader id="queries-title" title="Custom search queue" description="Ask the night run to look for something specific." />
        <CardBody className="flex flex-col gap-5">
          <CustomQueryForm segments={segments.map((s) => ({ id: s.id, label: s.label }))} />
          {data.queries.length ? (
            <ul className="flex flex-col divide-y divide-line-2 rounded-xl border border-line-2">
              {data.queries.map((q) => (
                <li key={q.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5">
                  <span className="min-w-0 flex-1 text-base text-tx-1">{q.query}</span>
                  <span className="label-mono">{q.segment_id}</span>
                  <Tag tone={QUERY_TONE[q.status] ?? 'neutral'}>{q.status}</Tag>
                  <span className="text-xs text-tx-3">{relativeAge(q.created_at, now)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </CardBody>
      </Card>
    </div>
  )
}
