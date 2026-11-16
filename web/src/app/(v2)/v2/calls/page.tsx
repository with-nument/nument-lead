import type { Metadata } from 'next'
import { Suspense } from 'react'
import { early, requireUser } from '@/lib/auth'
import { getCallsPage } from '@/lib/queries/email'
import { CallsSkeleton } from './calls-skeleton'
import { CallsView } from './calls-view'

export const metadata: Metadata = { title: 'Calls' }

/**
 * Every booked call (v2 only): today, coming up and the last 30 days, each with the engine's pre-call brief,
 * the offer to lead with and the plan page views. Notes go into a draft proposal for the engine to write.
 * One database call (calls_page, migration 0033) as the user.
 */
export default function CallsPage({ searchParams }: PageProps<'/v2/calls'>) {
  return (
    <Suspense fallback={<CallsSkeleton />}>
      <Calls searchParams={searchParams} />
    </Suspense>
  )
}

async function Calls({ searchParams }: Pick<PageProps<'/v2/calls'>, 'searchParams'>) {
  const callsP = early(getCallsPage())
  const [user, sp] = await Promise.all([requireUser(), searchParams])
  const calls = await callsP
  // ?lead=<id> opens that call's brief (Today's "Open brief").
  const lead = typeof sp.lead === 'string' ? sp.lead : null
  return <CallsView calls={calls} canAct={user.role === 'admin' || user.role === 'caller'} initialLead={lead} />
}
