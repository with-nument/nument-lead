import type { Metadata } from 'next'
import { Suspense } from 'react'
import { TodayDate } from '@/components/shell2/today-date'
import { Page } from '@/components/ui2/large-title'
import { early, requireUser } from '@/lib/auth'
import { istDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { canEdit } from '@/lib/roles'
import { getCallsPage, getInboxSummary } from '@/lib/queries/email'
import type { CallsPage, InboxSummary } from '@/lib/queries/email-data'
import { getHomeSummary, getOvernight } from '@/lib/queries/today'
import { approveReply } from './_today/actions'
import { firstStep, followupsFrom, headline, pipelineStats, startupsFrom, startupSummary, type TodayData } from './_today/build'
import { CallsSection } from './_today/calls'
import { callsFrom, overnightHealth, overnightStats, proposalsFrom, repliesFrom, toOvernight } from './_today/email'
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

/** How many replies Today lists; the rest wait in Inbox. */
const REPLIES_SHOWN = 5

const NO_CALLS: CallsPage = { today: [], upcoming: [], earlier: [] }
const NO_REPLIES: InboxSummary = { counts: { replies: 0, review: 0, done: 0 }, replies: [] }

/** The email reads must not take Today down with them: on an error the section is empty and the error logged. */
function orEmpty<T>(p: Promise<T>, empty: T, what: string): Promise<T> {
  return p.catch((e: unknown) => {
    console.error(`Today: ${what} failed`, e instanceof Error ? e.message : e)
    return empty
  })
}

async function Today() {
  // Every read starts with the session check and runs in parallel: home_summary (counts, send list, follow-ups),
  // inbox_page (replies waiting), calls_page (today's calls and drafted proposals) and today_overnight (the
  // card). All run as the user under Row Level Security, so a viewer gets no email.
  const summaryP = early(getHomeSummary())
  const inboxP = early(orEmpty(getInboxSummary(REPLIES_SHOWN), NO_REPLIES, 'inbox_page'))
  const callsP = early(orEmpty(getCallsPage(), NO_CALLS, 'calls_page'))
  const overnightP = early(getOvernight())
  const user = await requireUser()
  const [s, inbox, calls, overnightJson] = await Promise.all([summaryP, inboxP, callsP, overnightP])
  const now = new Date()
  const editable = canEdit(user.role)
  const overnight = toOvernight(overnightJson)

  const data: TodayData = {
    replies: repliesFrom(inbox.replies),
    replyTotal: inbox.counts.replies,
    calls: callsFrom(calls),
    proposals: proposalsFrom(calls, now),
    followups: followupsFrom(s, istDate(now)),
    startups: startupsFrom(s),
  }
  const head = headline(data, now)
  const first = firstStep(data)

  return (
    <Page title={head.title} compactTitle={head.compact} eyebrow={<TodayDate />} subtitle={head.subtitle}>
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-8">
        <div>
          <RepliesSection step={1} items={data.replies} total={inbox.counts.replies} primary={first === 'replies'} canEdit={editable} approve={approveReply} />
          <CallsSection step={2} items={data.calls} primary={first === 'calls'} />
          <ProposalsSection step={3} items={data.proposals} primary={first === 'proposals'} />
          <FollowupsSection step={4} items={data.followups} primary={first === 'followups'} canEdit={editable} />
          <StartupsSection step={5} items={data.startups} primary={first === 'startups'} canEdit={editable} summary={startupSummary(s)} />
        </div>
        {overnight ? (
          <OvernightCard title="Overnight" window="Since 6 pm yesterday" rows={overnightStats(overnight)} health={overnightHealth(overnight)} link={{ href: '/insights', label: 'See Insights' }} />
        ) : (
          <OvernightCard
            title="Your pipeline"
            window={s.kpis.overdue ? `${formatNumber(s.kpis.overdue)} overdue` : undefined}
            rows={pipelineStats(s)}
            link={{ href: '/insights', label: 'See Insights' }}
          />
        )}
      </div>
      <WelcomeGate userId={user.id} completedAt={user.tourCompletedAt} />
    </Page>
  )
}
