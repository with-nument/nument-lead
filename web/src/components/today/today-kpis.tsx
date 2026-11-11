import { KpiTile } from '@/components/ui/kpi-tile'
import { formatInr } from '@/lib/format'
import type { TodayKpis } from '@/lib/queries/today'

export function TodayKpiTiles({ kpis }: { kpis: TodayKpis }) {
  const money = kpis.wonThisMonthInr !== null
  return (
    <div className={money ? 'grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7' : 'grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6'}>
      <KpiTile label="Ready to send" value={kpis.ready} />
      <KpiTile label="Contacted this week" value={kpis.contactedThisWeek} />
      <KpiTile label="Talking" value={kpis.talking} />
      <KpiTile label="Discovery" value={kpis.discovery} />
      <KpiTile label="Proposals" value={kpis.proposals} />
      <KpiTile label="Overdue" value={kpis.overdue} tone={kpis.overdue > 0 ? 'alert' : 'default'} hint={kpis.overdue > 0 ? 'Past the due date' : undefined} />
      {money ? <KpiTile label="Won this month" value={formatInr(kpis.wonThisMonthInr)} tone="money" className="col-span-2 sm:col-span-1" /> : null}
    </div>
  )
}
