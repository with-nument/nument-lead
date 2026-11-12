import type { Metadata } from 'next'
import Link from 'next/link'
import { Suspense } from 'react'
import { Download } from 'lucide-react'
import { FilterPanel } from '@/components/leads/filter-panel'
import { LeadsTable, type LeadRowView } from '@/components/leads/leads-table'
import { MobileFilters } from '@/components/leads/mobile-filters'
import { Pagination } from '@/components/leads/pagination'
import { SaveViewButton, SavedViews } from '@/components/leads/saved-views'
import { SearchBox } from '@/components/leads/search-box'
import { buttonClasses } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton, SkeletonRows } from '@/components/ui/skeleton'
import { requireUser } from '@/lib/auth'
import { dueState, formatDate, istDate, relativeAge } from '@/lib/dates'
import { formatNumber, hostOf } from '@/lib/format'
import { activeFilterCount, filtersToQuery, parseLeadFilters } from '@/lib/leads-filters'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { PHONE_TYPE_LABEL, countryLabel, pitchLabel, signalLabel } from '@/lib/signals'
import { getCities, getLeadsPage, getSavedViews } from '@/lib/queries/leads'
import { getSegments, getTeam, segmentLabeler } from '@/lib/queries/shared'

export const metadata: Metadata = { title: 'Leads' }

export default function LeadsPage({ searchParams }: PageProps<'/leads'>) {
  return (
    <Suspense fallback={<LeadsSkeleton />}>
      <Leads searchParams={searchParams} />
    </Suspense>
  )
}

async function Leads({ searchParams }: Pick<PageProps<'/leads'>, 'searchParams'>) {
  const [user, sp] = await Promise.all([requireUser(), searchParams])
  const filters = parseLeadFilters(sp)
  const now = new Date()
  const today = istDate(now)
  const isAdmin = canSeeMoney(user.role)
  const [page, segments, team, cities, views] = await Promise.all([
    getLeadsPage(filters, { userId: user.id, today, withMoney: isAdmin }),
    getSegments(),
    getTeam(),
    getCities(filters.country),
    getSavedViews(user.id),
  ])
  const segmentOf = segmentLabeler(segments)
  const teamName = new Map(team.map((m) => [m.id, m.name]))
  const qs = filtersToQuery(filters, { page: 1 })

  const rows: LeadRowView[] = page.rows.map((r) => {
    const state = dueState(r.due_at, today)
    return {
      id: r.id,
      name: r.name,
      host: r.web_domain ?? hostOf(r.website),
      segment: segmentOf(r.segment_id),
      country: countryLabel(r.country),
      city: r.city ?? '',
      grade: r.grade,
      stage: r.stage,
      signal: r.top_signal_type ? signalLabel(r.top_signal_type) : '',
      signalAge: r.top_signal_at ? relativeAge(r.top_signal_at, now) : '',
      signalUrl: r.top_signal_url,
      score: r.total === null ? null : Math.round(Number(r.total)),
      pitch: pitchLabel(r.pitch_mode),
      phoneType: r.phone_e164 ? (PHONE_TYPE_LABEL[r.phone_type ?? 'unknown'] ?? '') : '',
      owner: r.owner_id ? (teamName.get(r.owner_id) ?? '') : '',
      activity: r.last_activity_at ? relativeAge(r.last_activity_at, now) : '',
      due: r.due_at ? (state === 'today' ? 'Today' : formatDate(r.due_at, now)) : '',
      dueState: state,
      ...(isAdmin ? { deal: r.deal_value_inr ?? null } : {}),
    }
  })

  const options = {
    segments: segments.map((s) => ({ id: s.id, label: s.label })),
    countries: [...new Set(segments.map((s) => s.country))],
    cities,
    team: team.map((m) => ({ id: m.id, name: m.name })),
  }
  const exportHref = `/leads/export${qs ? `?${qs}` : ''}`

  return (
    <>
      <PageHeader
        title="Leads"
        description={`${formatNumber(page.total)} ${page.total === 1 ? 'lead' : 'leads'}${activeFilterCount(filters) ? ' match these filters' : ''}`}
        actions={
          <>
            <SaveViewButton currentQs={qs} />
            {user.role !== 'viewer' ? (
              <a href={exportHref} className={buttonClasses('secondary')} download>
                <Download aria-hidden />
                Export CSV
              </a>
            ) : null}
          </>
        }
      />
      <div className="lg:grid lg:grid-cols-[208px_minmax(0,1fr)] lg:gap-6">
        <aside className="hidden lg:block" aria-label="Filters">
          <div className="sticky top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto pr-1 pb-6">
            <FilterPanel filters={filters} options={options} showOwner={user.role !== 'viewer'} />
            <SavedViews mine={views.mine} shared={views.shared} currentQs={qs} />
          </div>
        </aside>
        <div className="min-w-0">
          <div className="mb-3 flex gap-2">
            <SearchBox filters={filters} className="flex-1" />
            <MobileFilters filters={filters} options={options} showOwner={user.role !== 'viewer'} />
          </div>
          <Card>
            {rows.length ? (
              <>
                <LeadsTable rows={rows} filters={filters} canEdit={canEdit(user.role)} isAdmin={isAdmin} team={options.team} />
                <Pagination filters={filters} total={page.total} pageSize={page.pageSize} />
              </>
            ) : (
              <EmptyState
                text={activeFilterCount(filters) ? 'No leads match these filters.' : 'No leads yet. The engine adds them every morning.'}
                action={
                  activeFilterCount(filters) ? (
                    <Link href="/leads" className={buttonClasses('secondary', 'sm')}>
                      Clear filters
                    </Link>
                  ) : undefined
                }
              />
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function LeadsSkeleton() {
  return (
    <div aria-busy>
      <PageHeader title="Leads" />
      <div className="lg:grid lg:grid-cols-[208px_minmax(0,1fr)] lg:gap-6">
        <div className="hidden space-y-3 lg:block">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-4 w-3/4" />
          ))}
        </div>
        <div>
          <Skeleton className="mb-3 h-10 w-full rounded-full" />
          <Card>
            <SkeletonRows rows={8} />
          </Card>
        </div>
      </div>
    </div>
  )
}
