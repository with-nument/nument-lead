import type { Metadata } from 'next'
import { notFound, unstable_rethrow } from 'next/navigation'
import { Suspense } from 'react'
import { early, requireUser } from '@/lib/auth'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { getLeadConversation } from '@/lib/queries/email'
import { getLeadDetail, getProposals } from '@/lib/queries/lead'
import { getSegments, getTeam, segmentLabeler } from '@/lib/queries/shared'
import { approveReply, reopenReply } from './_lead/actions'
import { toLeadExtras, type SourceOf } from './_lead/extras'
import { LeadScreen, type Tab } from './_lead/lead-screen'
import { LeadSkeleton } from './_lead/skeleton'
import { toLeadView } from './_lead/model'

export const metadata: Metadata = { title: 'Lead' }

/**
 * One sample id, so the build can prerender the shell around this page (the shell reads the path). Every
 * real lead renders on request; the sample id is a nil UUID no lead has, so it would show Not found.
 */
export async function generateStaticParams() {
  return [{ id: '00000000-0000-4000-8000-000000000000' }]
}

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
  // The email side (lead_conversation: thread, offers, plan pages, startup profile) in parallel. If it fails the
  // page still shows the lead, without the thread.
  const conversationP = early(
    getLeadConversation(id).catch((e: unknown) => {
      unstable_rethrow(e)
      console.error('lead_conversation failed', e instanceof Error ? e.message : e)
      return null
    }),
  )
  const user = await requireUser()
  const isAdmin = canSeeMoney(user.role)
  const [detail, conversation, team, segments, proposals] = await Promise.all([
    detailP,
    conversationP,
    getTeam(),
    getSegments(),
    isAdmin ? getProposals(id) : Promise.resolve([]),
  ])
  if (!detail) notFound()
  const now = new Date()
  // Evidence ids in the startup profile point at facts and signals: their sources come from lead_detail.
  const sources: SourceOf = new Map([
    ...detail.facts.map((f) => [f.id, { url: f.url, at: f.created_at }] as const),
    ...detail.signals.map((sg) => [sg.id, { url: sg.url, at: sg.observed_at }] as const),
  ])
  const extras = {
    ...toLeadExtras(conversation, { contactName: detail.lead.contact_name ?? null, sources, now }),
    approveReply,
    reopenReply,
  }
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
      extras={extras}
    />
  )
}
