import { Card, CardHeader } from '@/components/ui/card'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton, SkeletonRows } from '@/components/ui/skeleton'

// Loading states for every app page. Each one has the page's real header and the outline of what
// streams in, so the frame never jumps when the data arrives. Used as the page's own Suspense
// fallback (part of the prerendered shell) and by the route's loading.tsx (shown at once on a
// navigation whose shell is not prefetched yet). The sidebar and top bar live in the layout and
// never repaint.

/** Today: KPI tiles, the send list and the follow-ups. */
export function TodayBody() {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="rounded-xl border border-line-2 bg-surface px-4 py-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-12" />
          </div>
        ))}
      </div>
      <Card className="mt-6">
        <CardHeader title="Send list" />
        <div className="mt-2 border-t border-line-2">
          <SkeletonRows rows={4} />
        </div>
      </Card>
      <Card className="mt-6">
        <CardHeader title="Follow-ups due" />
        <div className="mt-2 border-t border-line-2">
          <SkeletonRows rows={2} />
        </div>
      </Card>
    </>
  )
}

export function TodaySkeleton() {
  return (
    <div aria-busy>
      <PageHeader title="Today" />
      <TodayBody />
    </div>
  )
}

/** Leads: filters on the left, search and the table on the right. */
export function LeadsSkeleton() {
  return (
    <div aria-busy>
      <PageHeader title="Leads" />
      <div className="lg:grid lg:grid-cols-[208px_minmax(0,1fr)] lg:gap-6">
        <div className="hidden space-y-5 lg:block">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-9 w-full rounded-lg" />
            </div>
          ))}
        </div>
        <div className="min-w-0">
          <Skeleton className="mb-3 h-10 w-full rounded-full" />
          <Card>
            <div className="flex h-10 items-center gap-6 border-b border-line-2 px-4 sm:px-5">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-16" />
              <Skeleton className="hidden h-3 w-16 sm:block" />
              <Skeleton className="hidden h-3 w-20 md:block" />
            </div>
            <SkeletonRows rows={8} />
          </Card>
        </div>
      </div>
    </div>
  )
}

/** One lead: back link, name and place, the controls bar, then two columns of cards. */
export function LeadSkeleton() {
  return (
    <div aria-busy>
      <Skeleton className="mb-4 h-4 w-16" />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <Skeleton className="h-8 w-2/3 max-w-md" />
          <Skeleton className="mt-3 h-4 w-1/3" />
        </div>
        <Skeleton className="h-10 w-28 rounded-xl" />
      </div>
      <Skeleton className="mt-5 h-20 w-full rounded-2xl" />
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-6">
          <Card>
            <CardHeader title="Why this lead" />
            <SkeletonRows rows={3} />
          </Card>
          <Card>
            <CardHeader title="Message" />
            <div className="space-y-2 p-4 sm:p-5">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          </Card>
        </div>
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader title="Contact" />
            <SkeletonRows rows={2} />
          </Card>
          <Card>
            <CardHeader title="Notes" />
            <SkeletonRows rows={1} />
          </Card>
        </div>
      </div>
    </div>
  )
}

/** Pipeline: the filter row, then the stage columns. */
export function BoardBody() {
  return (
    <div aria-busy>
      <div className="mb-4 flex flex-wrap gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-36 rounded-full" />
        ))}
      </div>
      <div className="flex gap-3 overflow-hidden">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="w-72 shrink-0 rounded-2xl border border-line-2 bg-surface-2/60 p-3">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="mt-3 h-16 w-full rounded-xl" />
            <Skeleton className="mt-2 h-16 w-full rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  )
}

export const PIPELINE_TITLE = 'Pipeline'
export const PIPELINE_DESCRIPTION = 'Every lead after the first message. Drag a card to change its stage.'

export function PipelineSkeleton() {
  return (
    <>
      <PageHeader title={PIPELINE_TITLE} description={PIPELINE_DESCRIPTION} />
      <BoardBody />
    </>
  )
}

/** Insights: the filter bar, funnel and segment cards, then the table. */
export function InsightsBody() {
  return (
    <div aria-busy className="flex flex-col gap-6">
      <Skeleton className="h-10 w-full max-w-2xl rounded-full" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Funnel" />
          <SkeletonRows rows={4} />
        </Card>
        <Card>
          <CardHeader title="Contacted by segment" />
          <SkeletonRows rows={4} />
        </Card>
      </div>
      <Skeleton className="h-48 rounded-2xl" />
    </div>
  )
}

export const INSIGHTS_TITLE = 'Insights'
export const INSIGHTS_DESCRIPTION = 'What converts, how good the leads are, and what they cost.'

export function InsightsSkeleton() {
  return (
    <>
      <PageHeader title={INSIGHTS_TITLE} description={INSIGHTS_DESCRIPTION} />
      <InsightsBody />
    </>
  )
}

/** Engine: budget and run cards, then the segments and sources tables. */
export function EngineBody() {
  return (
    <div className="flex flex-col gap-6" aria-busy>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Budget" />
          <SkeletonRows rows={3} />
        </Card>
        <Card>
          <CardHeader title="Run now" />
          <SkeletonRows rows={3} />
        </Card>
      </div>
      <Card>
        <CardHeader title="Segments" />
        <div className="mt-3 border-t border-line-2">
          <SkeletonRows rows={4} />
        </div>
      </Card>
    </div>
  )
}

export const ENGINE_TITLE = 'Engine'
export const ENGINE_DESCRIPTION = 'Segments, budget, sources and runs. Changes apply from the next run.'

export function EngineSkeleton() {
  return (
    <>
      <PageHeader title={ENGINE_TITLE} description={ENGINE_DESCRIPTION} />
      <EngineBody />
    </>
  )
}

/** Inbox: the paste card, then the list of posts. */
export function InboxBody() {
  return (
    <div className="flex flex-col gap-6" aria-busy>
      <Card>
        <CardHeader title="Add a post" />
        <div className="space-y-3 p-4 sm:p-5">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-9 w-32 rounded-full" />
        </div>
      </Card>
      <Card>
        <CardHeader title="Posts" />
        <div className="mt-3 border-t border-line-2">
          <SkeletonRows rows={4} />
        </div>
      </Card>
    </div>
  )
}

export const INBOX_TITLE = 'Inbox'
export const INBOX_DESCRIPTION = 'Paste public posts where someone asks for help. The engine works from the text you paste and never opens LinkedIn or X.'

export function InboxSkeleton() {
  return (
    <>
      <PageHeader title={INBOX_TITLE} description={INBOX_DESCRIPTION} />
      <InboxBody />
    </>
  )
}

/** A settings tab (below the Settings header and tabs, which stay in the layout). */
export function SettingsBody() {
  return (
    <div className="flex flex-col gap-6" aria-busy>
      <Card>
        <SkeletonRows rows={3} />
      </Card>
    </div>
  )
}
