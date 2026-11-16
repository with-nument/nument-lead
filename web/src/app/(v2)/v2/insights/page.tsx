import type { Metadata } from 'next'
import { connection } from 'next/server'
import { Suspense } from 'react'
import { Columns, Panel, Row, Section } from '@/app/(v2)/v2/_parts/section'
import { cx } from '@/components/ui2/cx'
import { Page } from '@/components/ui2/large-title'
import { Skeleton } from '@/components/ui2/skeleton'
import { early, requireUser } from '@/lib/auth'
import { formatDate, istDate } from '@/lib/dates'
import { formatInr, formatNumber, formatPercent } from '@/lib/format'
import { GROUPS, MIN_SAMPLE, getInsights, type InsightsCosts } from '@/lib/queries/insights'
import { getSegments, segmentLabeler } from '@/lib/queries/shared'
import { canSeeMoney } from '@/lib/roles'
import { countryLabel, pitchLabel, signalLabel } from '@/lib/signals'
import { GroupSelect, InsightsFilters } from './_parts/filters'
import { barShare, parseInsightsQuery, pct } from './filters'

export const metadata: Metadata = { title: 'Insights' }

const SUBTITLE = 'What turns into replies, meetings and won work.'

export default function InsightsPage({ searchParams }: PageProps<'/v2/insights'>) {
  return (
    <Page title="Insights" subtitle={SUBTITLE}>
      <Suspense fallback={<InsightsSkeleton />}>
        <Insights searchParams={searchParams} />
      </Suspense>
    </Page>
  )
}

/** One horizontal bar row: label, a grey bar on its own track, the number and a quiet note. */
function Bar({ label, value, max, note, strong }: { label: string; value: number; max: number; note?: string; strong?: boolean }) {
  return (
    <li className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)_auto] items-center gap-3 py-2 text-[15px] lg:text-[14px]">
      <span className="truncate text-label-2">{label}</span>
      <span aria-hidden className="h-2 overflow-hidden rounded-full bg-fill-2">
        <span className={cx('block h-full rounded-full', strong ? 'bg-label-2' : 'bg-label-3')} style={{ width: `${barShare(value, max) * 100}%` }} />
      </span>
      <span className="min-w-[4.5rem] text-right tabular-nums">
        <span className="text-label-1">{formatNumber(value)}</span>
        {note ? <span className="ml-1.5 text-label-3">{note}</span> : null}
      </span>
    </li>
  )
}

async function Insights({ searchParams }: Pick<PageProps<'/v2/insights'>, 'searchParams'>) {
  // Request time only (the period reads the clock), then the one database call can start.
  const [sp] = await Promise.all([searchParams, connection()])
  const now = new Date()
  const q = parseInsightsQuery(sp, istDate(now))
  // insights_summary runs as the user (Row Level Security; costs only for admins) and starts while the session is checked.
  const insights = early(getInsights({ from: q.from, to: q.to, seg: q.seg, country: q.country, group: q.group }))
  const user = await requireUser()
  const [data, segments] = await Promise.all([insights, getSegments()])
  const costs = canSeeMoney(user.role) ? data.costs : null
  const segmentOf = segmentLabeler(segments)
  const groupLabel = (id: string) => {
    if (id === 'unknown') return 'Not set'
    if (q.group === 'segment') return segmentOf(id)
    if (q.group === 'country') return countryLabel(id)
    if (q.group === 'signal') return id === 'none' ? 'No live signal' : signalLabel(id)
    if (q.group === 'pitch') return pitchLabel(id) || id
    return id
  }
  const t = data.total
  const countries = [...new Set(segments.map((s) => s.country))].filter(Boolean).map((c) => ({ id: c, label: countryLabel(c) }))
  const period = `${formatDate(q.from, now)} to ${formatDate(q.to, now)}`

  return (
    <>
      <InsightsFilters value={q} segments={segments.map((s) => ({ id: s.id, label: s.label }))} countries={countries} />
      {t.leads === 0 ? (
        <Panel>
          <div className="px-6 py-14 text-center">
            <h2 className="type-headline text-label-1">No leads in this period</h2>
            <p className="type-subhead mt-1.5 text-label-3">Nothing was added from {period}. Try a longer period or all segments.</p>
          </div>
        </Panel>
      ) : (
        <div className="flex flex-col gap-7">
          <Columns>
            <Section id="funnel-title" title="Funnel" description={`${formatNumber(t.leads)} leads added, ${period}. Percentages are of contacted leads.`}>
              <Panel>
                <ul className="px-4 py-2 lg:px-5">
                  <Bar label="Leads added" value={t.leads} max={t.leads} />
                  <Bar label="Contacted" value={t.contacted} max={t.leads} note={pct(t.contacted, t.leads)} strong />
                  <Bar label="Replied" value={t.replied} max={t.leads} note={pct(t.replied, t.contacted)} strong />
                  <Bar label="Meeting" value={t.meetings} max={t.leads} note={pct(t.meetings, t.contacted)} strong />
                  <Bar label="Proposal" value={t.proposals} max={t.leads} note={pct(t.proposals, t.contacted)} strong />
                  <Bar label="Won" value={t.won} max={t.leads} note={pct(t.won, t.contacted)} strong />
                </ul>
              </Panel>
            </Section>
            <Section id="seg-title" title="Contacted by segment" description="With the share that replied.">
              <Panel>
                {data.bySegment.length ? (
                  <ul className="px-4 py-2 lg:px-5">
                    {data.bySegment.map((s) => (
                      <Bar
                        key={s.id}
                        label={segmentOf(s.id) || 'Not set'}
                        value={s.contacted}
                        max={Math.max(...data.bySegment.map((x) => x.contacted))}
                        note={s.contacted ? `${pct(s.replied, s.contacted)} replied` : undefined}
                      />
                    ))}
                  </ul>
                ) : (
                  <Row>
                    <span className="block text-label-3">Nobody contacted yet.</span>
                  </Row>
                )}
              </Panel>
            </Section>
          </Columns>

          <Section
            id="works-title"
            title="What works"
            description={`Reply, meeting and win rates of contacted leads. Fewer than ${MIN_SAMPLE} contacted is too few to judge.`}
            action={<GroupSelect value={q} groups={Object.entries(GROUPS).map(([value, label]) => ({ value, label }))} />}
          >
            <Panel>
              <div aria-hidden className="hidden grid-cols-[minmax(0,1fr)_repeat(4,6.5rem)] gap-3 px-5 py-2.5 text-[13px] text-label-3 sm:grid">
                <span>{GROUPS[q.group]}</span>
                <span className="text-right">Contacted</span>
                <span className="text-right">Replied</span>
                <span className="text-right">Meeting</span>
                <span className="text-right">Won</span>
              </div>
              {data.byGroup.length ? (
                data.byGroup.map((g, i) => {
                  const thin = g.contacted < MIN_SAMPLE
                  return (
                    <WorksRow
                      key={g.id}
                      label={groupLabel(g.id)}
                      thin={thin}
                      first={i === 0}
                      cells={[formatNumber(g.contacted), pct(g.replied, g.contacted) || 'None', pct(g.meetings, g.contacted) || 'None', pct(g.won, g.contacted) || 'None']}
                    />
                  )
                })
              ) : (
                <Row>
                  <span className="block text-label-3">Nothing to compare yet.</span>
                </Row>
              )}
            </Panel>
          </Section>

          <Section id="quality-title" title="Lead quality">
            <Panel divided={false}>
              <div className="grid grid-cols-2 gap-px bg-separator lg:grid-cols-4">
              <Stat label="Own phone found" value={formatPercent(data.quality.ownPhoneRate) || 'None'} hint="Published on their own website" />
              <Stat label="Wrong contact" value={formatPercent(data.quality.wrongRate) || 'None'} hint="Of contacted leads" alert={(data.quality.wrongRate ?? 0) > 0.1} />
              <Stat label="Median signal age" value={data.quality.medianSignalAgeDays === null ? 'None' : `${Math.round(data.quality.medianSignalAgeDays)} days`} hint="When the lead was added" />
              <Stat label="Thumbs up" value={formatPercent(data.quality.thumbsUpRate) || 'None'} hint={`${formatNumber(data.quality.votes)} votes`} />
              </div>
            </Panel>
          </Section>
        </div>
      )}
      {costs ? <Costs costs={costs} now={now} /> : null}
    </>
  )
}

function WorksRow({ label, thin, cells, first }: { label: string; thin: boolean; cells: string[]; first: boolean }) {
  const [contacted, replied, meeting, won] = cells
  return (
    <div className={cx('px-4 py-3 text-[15px] sm:grid sm:grid-cols-[minmax(0,1fr)_repeat(4,6.5rem)] sm:items-center sm:gap-3 lg:px-5 lg:text-[14.5px]', thin ? 'text-label-3' : 'text-label-1', first && 'max-sm:shadow-none')}>
      <p className="truncate">
        {label}
        {thin ? <span className="type-caption ml-2 text-label-3">too few to judge</span> : null}
      </p>
      <p className="type-caption text-label-3 tabular-nums sm:hidden">
        {contacted} contacted · {replied} replied · {meeting} meeting · {won} won
      </p>
      {cells.map((c, i) => (
        <span key={i} className="hidden text-right tabular-nums sm:block">
          {c}
        </span>
      ))}
    </div>
  )
}

function Stat({ label, value, hint, alert }: { label: string; value: string; hint: string; alert?: boolean }) {
  return (
    <div className="flex flex-col gap-1 bg-panel p-4 lg:p-5">
      <span className="type-subhead text-label-3 lg:text-[13px]">{label}</span>
      <span className={cx('text-[22px] leading-7 font-semibold tracking-[-0.01em] tabular-nums', alert ? 'text-status-bad' : 'text-label-1')}>{value}</span>
      <span className="type-caption text-label-3">{hint}</span>
    </div>
  )
}

/** Admins only: spend per day as grey columns under the daily cap, then the unit costs. */
function Costs({ costs, now }: { costs: InsightsCosts; now: Date }) {
  const max = Math.max(costs.cap, ...costs.days.map((d) => d.inr))
  return (
    <Section id="cost-title" title="Cost" description={`${formatInr(costs.spend) || '₹0'} spent in this period. Admins only.`} className="mt-7">
      <Panel>
        <div className="px-4 pt-5 pb-3 lg:px-5">
          {costs.days.length ? (
            <>
              <div role="img" aria-label={`Spend per day against the ${formatInr(costs.cap)} daily cap`} className="relative flex h-32 items-end gap-[2px]">
                <span aria-hidden className="absolute inset-x-0 border-t border-dashed border-separator-strong" style={{ bottom: `${(costs.cap / max) * 100}%` }} />
                {costs.days.map((d) => (
                  <span
                    key={d.day}
                    title={`${formatDate(d.day, now)}: ${formatInr(d.inr)}`}
                    className={cx('min-w-0 flex-1 rounded-t-[3px]', d.inr > costs.cap ? 'bg-status-bad' : 'bg-label-3 opacity-50')}
                    style={{ height: `${max > 0 ? Math.max(d.inr > 0 ? 2 : 0, (d.inr / max) * 100) : 0}%` }}
                  />
                ))}
              </div>
              <div className="type-caption mt-2 flex justify-between text-label-3">
                <span>{formatDate(costs.days[0]!.day, now)}</span>
                <span>Daily cap {formatInr(costs.cap)}</span>
                <span>{formatDate(costs.days[costs.days.length - 1]!.day, now)}</span>
              </div>
            </>
          ) : (
            <p className="type-subhead pb-2 text-label-3">No spend in this period.</p>
          )}
        </div>
        <div className="grid grid-cols-1 gap-px bg-separator sm:grid-cols-3">
          <Stat label="Per researched business" value={costs.perResearched === null ? 'None' : formatInr(Math.round(costs.perResearched * 100) / 100)} hint={`${formatNumber(costs.researched)} researched`} />
          <Stat label="Per good lead (A or B)" value={costs.perGoodLead === null ? 'None' : formatInr(costs.perGoodLead)} hint={`${formatNumber(costs.goodLeads)} good leads`} />
          <Stat label="Per won client" value={costs.perWon === null ? 'None' : formatInr(costs.perWon)} hint={`${formatNumber(costs.won)} won`} />
        </div>
      </Panel>
    </Section>
  )
}

/** The filters row, then the two bar panels and the list, as they will appear. */
function InsightsSkeleton() {
  const panel = (rows: number) => (
    <div className="flex flex-col">
      <Skeleton className="mb-3 ml-1 h-4 w-28" />
      <div role="presentation" className="material-panel flex flex-col gap-4 overflow-hidden rounded-[20px] px-5 py-5">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-2 flex-1" />
            <Skeleton className="h-3 w-10" />
          </div>
        ))}
      </div>
    </div>
  )
  return (
    <div role="status" aria-label="Loading insights">
      <div className="mb-7 flex flex-wrap gap-2">
        <Skeleton className="h-9 w-[300px] rounded-control" />
        <Skeleton className="h-9 w-48 rounded-control" />
        <Skeleton className="h-9 w-40 rounded-control" />
      </div>
      <div className="flex flex-col gap-7">
        <div className="grid items-start gap-7 lg:grid-cols-2">
          {panel(6)}
          {panel(5)}
        </div>
        {panel(4)}
      </div>
    </div>
  )
}

