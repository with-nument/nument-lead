import type { Metadata } from 'next'
import { Suspense } from 'react'
import { TodayDate } from '@/components/shell2/today-date'
import { Page } from '@/components/ui2/large-title'
import { early, requireUser } from '@/lib/auth'
import { istDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { canEdit } from '@/lib/roles'
import { getHomeSummary } from '@/lib/queries/today'
import { firstStep, followupsFrom, headline, pipelineStats, startupsFrom, startupSummary, type TodayData } from './_today/build'
import { CallsSection } from './_today/calls'
import { FollowupsSection } from './_today/followups'
import { OvernightCard } from './_today/overnight'
import { ProposalsSection } from './_today/proposals'
import { RepliesSection } from './_today/replies'
import { TodaySkeleton } from './_today/skeleton'
import { StartupsSection } from './_today/startups'
import { WelcomeGate } from './_today/welcome-gate'

export const metadata: Metadata = { title: 'Today' }

export default function TodayPage() {
  return (
    <Suspense fallback={<TodaySkeleton />}>
      <Today />
    </Suspense>
  )
}

async function Today() {
  // One database call (home_summary) for everything below, started with the session check.
  const summary = early(getHomeSummary())
  const user = await requireUser()
  const s = await summary
  const now = new Date()
  const editable = canEdit(user.role)

  // Replies, calls and proposals come from the email tables (lane W3); until then they are empty.
  const data: TodayData = { replies: [], calls: [], proposals: [], followups: followupsFrom(s, istDate(now)), startups: startupsFrom(s) }
  const first = firstStep(data)
  const head = headline(data, now)

  return (
    <Page title={head.title} compactTitle={head.compact} eyebrow={<TodayDate />} subtitle={head.subtitle}>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-8">
        <div>
          <RepliesSection step={1} items={data.replies} primary={first === 'replies'} canEdit={editable} />
          <CallsSection step={2} items={data.calls} primary={first === 'calls'} />
          <ProposalsSection step={3} items={data.proposals} primary={first === 'proposals'} />
          <FollowupsSection step={4} items={data.followups} primary={first === 'followups'} canEdit={editable} />
          <StartupsSection step={5} items={data.startups} primary={first === 'startups'} canEdit={editable} summary={startupSummary(s)} />
        </div>
        <OvernightCard
          title="Your pipeline"
          window={s.kpis.overdue ? `${formatNumber(s.kpis.overdue)} overdue` : undefined}
          rows={pipelineStats(s)}
          link={{ href: '/insights', label: 'See Insights' }}
        />
      </div>
      <WelcomeGate userId={user.id} completedAt={user.tourCompletedAt} />
    </Page>
  )
}
