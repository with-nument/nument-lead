import type { Metadata } from 'next'
import { Suspense } from 'react'
import { BarList, rate } from '@/components/insights/bars'
import { CostChart } from '@/components/insights/cost-chart'
import { InsightFilters } from '@/components/insights/insight-filters'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { KpiTile } from '@/components/ui/kpi-tile'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { requireUser } from '@/lib/auth'
import { addDays, daysBetween, formatDate, istDate } from '@/lib/dates'
import { formatInr, formatNumber, formatPercent } from '@/lib/format'
import { canSeeMoney } from '@/lib/roles'
import { countryLabel, pitchLabel, signalLabel } from '@/lib/signals'
import { GROUPS, MIN_SAMPLE, getCosts, getInsights, type GroupKey } from '@/lib/queries/insights'
import { getSegments, segmentLabeler } from '@/lib/queries/shared'
import { cn } from '@/lib/cn'

export const metadata: Metadata = { title: 'Insights' }

const DAY = /^\d{4}-\d{2}-\d{2}$/

export default function InsightsPage({ searchParams }: PageProps<'/insights'>) {
  return (
    <>
      <PageHeader title="Insights" description="What converts, how good the leads are, and what they cost." />
      <Suspense fallback={<InsightsSkeleton />}>
        <Insights searchParams={searchParams} />
      </Suspense>
    </>
  )
}

async function Insights({ searchParams }: Pick<PageProps<'/insights'>, 'searchParams'>) {
  const [user, sp] = await Promise.all([requireUser(), searchParams])
  const one = (k: string) => (typeof sp[k] === 'string' ? (sp[k] as string) : '')
  const now = new Date()
  const today = istDate(now)
  const daysParam = one('days')
  const custom = DAY.test(one('from')) && DAY.test(one('to')) && one('from') <= one('to')
  const span = ['7', '30', '90'].includes(daysParam) ? Number(daysParam) : 30
  const from = custom ? one('from') : addDays(today, -(span - 1))
  const to = custom ? one('to') : today
  const group = (one('group') in GROUPS ? one('group') : 'segment') as GroupKey
  const filters = {
    from: daysBetween(from, to) > 366 ? addDays(to, -366) : from,
    to,
    seg: /^[a-z0-9-]{1,40}$/.test(one('seg')) ? one('seg') : '',
    country: /^[a-z]{2}$/.test(one('country')) ? one('country') : '',
    group,
  }
  const isAdmin = canSeeMoney(user.role)
  const [data, segments, costs] = await Promise.all([getInsights(filters), getSegments(), isAdmin ? getCosts(filters) : Promise.resolve(null)])
  const segmentOf = segmentLabeler(segments)
  const groupLabel = (id: string) =>
    id === 'unknown'
      ? 'Not set'
      : group === 'segment'
        ? segmentOf(id)
        : group === 'country'
          ? countryLabel(id)
          : group === 'signal'
            ? id === 'none'
              ? 'No live signal'
              : signalLabel(id)
            : group === 'pitch'
              ? pitchLabel(id)
              : id
  const t = data.total

  return (
    <>
      <InsightFilters
        value={{ from: filters.from, to: filters.to, seg: filters.seg, country: filters.country, group, preset: custom ? 'custom' : String(span) }}
        segments={segments.map((s) => ({ id: s.id, label: s.label }))}
        countries={[...new Set(segments.map((s) => s.country))]}
        groups={Object.entries(GROUPS).map(([value, label]) => ({ value, label }))}
      />

      {t.leads === 0 ? (
        <Card>
          <EmptyState text={`No leads were added between ${formatDate(filters.from, now)} and ${formatDate(filters.to, now)}.`} />
        </Card>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card aria-labelledby="funnel-title">
              <CardHeader id="funnel-title" title="Funnel" description={`${formatNumber(t.leads)} leads added. Percentages are of contacted leads.`} />
              <CardBody>
                <BarList
                  label="Funnel"
                  max={t.contacted}
                  rows={[
                    { key: 'contacted', label: 'Contacted', value: t.contacted, note: rate(t.contacted, t.leads) + ' of leads' },
                    { key: 'talking', label: 'Talking', value: t.replied, note: rate(t.replied, t.contacted) },
                    { key: 'discovery', label: 'Discovery', value: t.meetings, note: rate(t.meetings, t.contacted) },
                    { key: 'proposal', label: 'Proposal', value: t.proposals, note: rate(t.proposals, t.contacted) },
                    { key: 'won', label: 'Won', value: t.won, note: rate(t.won, t.contacted) },
                  ]}
                />
              </CardBody>
            </Card>
            <Card aria-labelledby="segments-title">
              <CardHeader id="segments-title" title="Contacted by segment" description="With the share that replied." />
              <CardBody>
                <BarList
                  label="Contacted by segment"
                  rows={data.bySegment.map((s) => ({ key: s.id, label: segmentOf(s.id), value: s.contacted, note: s.contacted ? `${rate(s.replied, s.contacted)} replied` : undefined }))}
                />
              </CardBody>
            </Card>
          </div>

          <Card aria-labelledby="works-title">
            <CardHeader id="works-title" title={`What works · by ${GROUPS[group].toLowerCase()}`} description={`Rows with fewer than ${MIN_SAMPLE} contacted leads are too few to judge.`} />
            <div className="mt-3 overflow-x-auto border-t border-line-2">
              <table className="w-full text-left text-base">
                <thead>
                  <tr>
                    {[GROUPS[group], 'Contacted', 'Reply rate', 'Meeting rate', 'Win rate'].map((h, i) => (
                      <th key={h} scope="col" className={cn('label-mono h-10 border-b border-line-2 px-3 font-normal whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5', i > 0 && 'text-right')}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.byGroup.map((g) => {
                    const thin = g.contacted < MIN_SAMPLE
                    return (
                      <tr key={g.id} className={cn('border-b border-line-2 last:border-b-0', thin && 'text-tx-3')}>
                        <td className="h-11 px-3 pl-4 sm:pl-5">
                          <span className={cn(!thin && 'text-tx-1')}>{groupLabel(g.id)}</span>
                          {thin ? <span className="ml-2 text-xs text-tx-4">too few to judge</span> : null}
                        </td>
                        <td className="px-3 text-right tabular">{formatNumber(g.contacted)}</td>
                        <td className="px-3 text-right tabular">{rate(g.replied, g.contacted)}</td>
                        <td className="px-3 text-right tabular">{rate(g.meetings, g.contacted)}</td>
                        <td className="px-3 pr-4 text-right tabular sm:pr-5">{rate(g.won, g.contacted)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <section aria-labelledby="quality-title">
            <h2 id="quality-title" className="label-mono mb-2">
              Lead quality
            </h2>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <KpiTile label="Own phone found" value={formatPercent(data.quality.ownPhoneRate) || 'None'} hint="Published on their own website" />
              <KpiTile
                label="Wrong contact"
                value={formatPercent(data.quality.wrongRate) || 'None'}
                hint="Of contacted leads"
                tone={(data.quality.wrongRate ?? 0) > 0.1 ? 'alert' : 'default'}
              />
              <KpiTile
                label="Median signal age"
                value={data.quality.medianSignalAgeDays === null ? 'None' : `${Math.round(data.quality.medianSignalAgeDays)}d`}
                hint="When the lead was added"
              />
              <KpiTile label="Thumbs up" value={formatPercent(data.quality.thumbsUpRate) || 'None'} hint={`${formatNumber(data.quality.votes)} votes`} />
            </div>
          </section>
        </div>
      )}

      {costs ? (
        <Card className="mt-6" aria-labelledby="cost-title">
          <CardHeader id="cost-title" title="Cost" description={`${formatInr(costs.spend)} spent in this period. Admins only.`} />
          <CardBody className="flex flex-col gap-5">
            <CostChart data={costs.days.map((d) => ({ ...d, label: formatDate(d.day, now) }))} cap={costs.cap} />
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <KpiTile label="Per researched business" value={costs.perResearched === null ? 'None' : formatInr(Math.round(costs.perResearched * 100) / 100)} hint={`${formatNumber(costs.researched)} researched`} tone="money" />
              <KpiTile label="Per good lead (A or B)" value={costs.perGoodLead === null ? 'None' : formatInr(costs.perGoodLead)} hint={`${formatNumber(costs.goodLeads)} good leads`} tone="money" />
              <KpiTile label="Per won client" value={costs.perWon === null ? 'None' : formatInr(costs.perWon)} hint={`${formatNumber(costs.won)} won`} tone="money" />
            </div>
          </CardBody>
        </Card>
      ) : null}
    </>
  )
}

function InsightsSkeleton() {
  return (
    <div aria-busy className="flex flex-col gap-6">
      <Skeleton className="h-10 w-full max-w-2xl rounded-full" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-64 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
      <Skeleton className="h-48 rounded-2xl" />
    </div>
  )
}
