import type { Metadata } from 'next'
import { Suspense } from 'react'
import { early, requireUser } from '@/lib/auth'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { getBoard } from '@/lib/queries/pipeline'
import { DealsBoard } from './_board/deals-board'
import { toBoardView } from './_board/model'
import { DealsSkeleton } from './_board/skeleton'

export const metadata: Metadata = { title: 'Deals' }

// The most recent closed deals, for the folded Closed row (the counts cover them all).
const CLOSED_PER_STAGE = 30

/** The new design's Deals page (served at /deals when the new design is on; src/lib/ui-flag.ts). */
export default function DealsPage() {
  return (
    <Suspense fallback={<DealsSkeleton />}>
      <Deals />
    </Suspense>
  )
}

async function Deals() {
  // One database call (deals_board): every open deal and the recent closed ones, money only for admins. It
  // runs as the user (RLS) and starts while the session is checked.
  const boardP = early(getBoard({ seg: '', country: '', owner: '', overdue: false }, { closedPerStage: CLOSED_PER_STAGE }))
  const user = await requireUser()
  const isAdmin = canSeeMoney(user.role)
  const board = await boardP
  return <DealsBoard view={toBoardView(board, { now: new Date(), isAdmin })} canEdit={canEdit(user.role)} isAdmin={isAdmin} />
}
