import type { Metadata } from 'next'
import { Suspense } from 'react'
import { early, requireUser } from '@/lib/auth'
import { getInboxPage } from '@/lib/queries/email'
import { isInboxTab, type InboxPage } from '@/lib/queries/email-data'
import { InboxSkeleton } from './inbox-skeleton'
import { InboxView } from './inbox-view'

export const metadata: Metadata = { title: 'Inbox' }

/**
 * The email Inbox (v2 only): replies with a drafted answer, first emails waiting for review, and what went out.
 * One database call (inbox_page, migration 0033) as the user; approving goes through review_message and the
 * engine's outreach run sends it. Viewers see no email (Row Level Security), so they get the empty state.
 */
export default function InboxPage({ searchParams }: PageProps<'/v2/inbox'>) {
  return (
    <Suspense fallback={<InboxSkeleton />}>
      <Inbox searchParams={searchParams} />
    </Suspense>
  )
}

async function Inbox({ searchParams }: Pick<PageProps<'/v2/inbox'>, 'searchParams'>) {
  const sp = await searchParams
  const tab = isInboxTab(sp.tab) ? sp.tab : 'replies'
  const pageP = early(getInboxPage(tab))
  const user = await requireUser()
  const page: InboxPage = await pageP
  return <InboxView key={tab} initial={page} canAct={user.role === 'admin' || user.role === 'caller'} />
}
