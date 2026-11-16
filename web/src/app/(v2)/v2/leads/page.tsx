import type { Metadata } from 'next'
import { Suspense } from 'react'
import { early, requireUser } from '@/lib/auth'
import { parseLeadFilters } from '@/lib/leads-filters'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { getLeadsPage } from '@/lib/queries/leads'
import { getSegments, getTeam, segmentLabeler } from '@/lib/queries/shared'
import { LeadsList } from './_list/leads-list'
import { LeadsSkeleton } from './_list/skeleton'
import { scopeOf, toRow } from './_list/model'

export const metadata: Metadata = { title: 'Leads' }

/** The new design's Leads list (served at /leads when the new design is on; src/lib/ui-flag.ts). */
export default function LeadsPage({ searchParams }: PageProps<'/v2/leads'>) {
  return (
    <Suspense fallback={<LeadsSkeleton />}>
      <Leads searchParams={searchParams} />
    </Suspense>
  )
}

async function Leads({ searchParams }: Pick<PageProps<'/v2/leads'>, 'searchParams'>) {
  const filters = parseLeadFilters(await searchParams)
  // One database call (leads_page) for the rows, the total, the cities and the saved views. It runs as the
  // user (RLS) and starts while the session is checked.
  const pageP = early(getLeadsPage(filters))
  const user = await requireUser()
  const [page, segments, team] = await Promise.all([pageP, getSegments(), getTeam()])
  const now = new Date()
  const segmentOf = segmentLabeler(segments)
  return (
    <LeadsList
      rows={page.rows.map((r) => toRow(r, segmentOf, now))}
      filters={filters}
      total={page.total}
      pageSize={page.pageSize}
      newCount={scopeOf(filters, now) === 'new' ? page.total : null}
      options={{
        segments: segments.map((s) => ({ id: s.id, label: s.label })),
        countries: [...new Set(segments.map((s) => s.country))],
        cities: page.cities,
        team: team.map((m) => ({ id: m.id, name: m.name })),
        showOwner: user.role !== 'viewer',
      }}
      views={page.views}
      canEdit={canEdit(user.role)}
      isAdmin={canSeeMoney(user.role)}
      canExport={user.role !== 'viewer'}
    />
  )
}
