import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { Suspense } from 'react'
import { early, requireUser } from '@/lib/auth'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { getLeadDetail, getProposals } from '@/lib/queries/lead'
import { getSegments, getTeam, segmentLabeler } from '@/lib/queries/shared'
import { LeadScreen, type Tab } from './_lead/lead-screen'
import { LeadSkeleton } from './_lead/skeleton'
import { toLeadView } from './_lead/model'

export const metadata: Metadata = { title: 'Lead' }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const TABS = new Set<Tab>(['conversation', 'why', 'people', 'activity'])

/** The new design's lead page (served at /leads/[id] when the new design is on; src/lib/ui-flag.ts). */
export default function LeadPage({ params, searchParams }: PageProps<'/v2/leads/[id]'>) {
  return (
    <Suspense fallback={<LeadSkeleton />}>
      <Lead params={params} searchParams={searchParams} />
    </Suspense>
  )
}

async function Lead({ params, searchParams }: Pick<PageProps<'/v2/leads/[id]'>, 'params' | 'searchParams'>) {
  const [{ id }, sp] = await Promise.all([params, searchParams])
  if (!UUID.test(id)) notFound()
  // One database call (lead_detail) for the whole lead, money included for admins. It runs as the user
  // (RLS), so it starts now, before the session check. Unverified facts only when an admin asks.
  const wantsUnverified = sp.unverified === '1'
  const detailP = early(getLeadDetail(id, { includeUnverified: wantsUnverified }))
  const user = await requireUser()
  const isAdmin = canSeeMoney(user.role)
  const [detail, team, segments, proposals] = await Promise.all([detailP, getTeam(), getSegments(), isAdmin ? getProposals(id) : Promise.resolve([])])
  if (!detail) notFound()
  const now = new Date()
  const view = toLeadView(detail, { now, isAdmin, names: new Map(team.map((m) => [m.id, m.name])), segmentOf: segmentLabeler(segments) })
  const mine = detail.feedback.find((f) => f.user_id === user.id) ?? null
  const tab = typeof sp.tab === 'string' && TABS.has(sp.tab as Tab) ? (sp.tab as Tab) : null
  return (
    <LeadScreen
      key={view.id}
      view={view}
      canEdit={canEdit(user.role)}
      isAdmin={isAdmin}
      includeUnverified={isAdmin && wantsUnverified}
      team={team.map((m) => ({ id: m.id, name: m.name }))}
      proposals={proposals.map((p) => ({ path: p.path, name: p.name, size: p.size }))}
      myFeedback={mine ? { rating: mine.rating, reason: mine.reason } : null}
      initialTab={tab}
    />
  )
}
