import type { Metadata } from 'next'
import { Suspense } from 'react'
import { BoardFilters } from '@/components/pipeline/board-filters'
import { Board, type CardView } from '@/components/pipeline/board'
import { AutoRefresh } from '@/components/shell/auto-refresh'
import { PageHeader } from '@/components/ui/page-header'
import { BoardBody, PIPELINE_DESCRIPTION, PIPELINE_TITLE } from '@/components/skeletons'
import { claimedUserId, early, requireUser } from '@/lib/auth'
import { dueState, formatDate, istDate } from '@/lib/dates'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { getBoard, withBoardDealValues } from '@/lib/queries/pipeline'
import { getSegments, getTeam } from '@/lib/queries/shared'

export const metadata: Metadata = { title: 'Pipeline' }

const UUID = /^[0-9a-f-]{36}$/i

export default function PipelinePage({ searchParams }: PageProps<'/pipeline'>) {
  return (
    <>
      <PageHeader title={PIPELINE_TITLE} description={PIPELINE_DESCRIPTION} />
      <Suspense fallback={<BoardBody />}>
        <Pipeline searchParams={searchParams} />
      </Suspense>
    </>
  )
}

async function Pipeline({ searchParams }: Pick<PageProps<'/pipeline'>, 'searchParams'>) {
  const [sp, userId] = await Promise.all([searchParams, claimedUserId()])
  const one = (k: string) => (typeof sp[k] === 'string' ? (sp[k] as string) : '')
  const owner = one('owner')
  const filters = {
    seg: /^[a-z0-9-]{1,40}$/.test(one('seg')) ? one('seg') : '',
    country: /^[a-z]{2}$/.test(one('country')) ? one('country') : '',
    owner: owner === 'me' || owner === 'none' || UUID.test(owner) ? owner : '',
    overdue: one('overdue') === '1',
  }
  const now = new Date()
  const today = istDate(now)
  // The board runs as the user (RLS) and starts while the session is checked.
  const board = early(getBoard(filters, { userId: userId ?? '', today }))
  const user = await requireUser()
  const isAdmin = canSeeMoney(user.role)
  const [cards, segments, team] = await Promise.all([isAdmin ? board.then(withBoardDealValues) : board, getSegments(), getTeam()])
  const names = new Map(team.map((m) => [m.id, m.name]))
  const views: CardView[] = cards.map((c) => {
    const state = dueState(c.dueAt, today)
    return {
      id: c.id,
      name: c.name,
      city: c.city,
      grade: c.grade,
      stage: c.stage,
      nextStep: c.nextStep,
      due: c.dueAt ? (state === 'today' ? 'Today' : formatDate(c.dueAt, now)) : '',
      overdue: state === 'overdue',
      owner: c.ownerId ? (names.get(c.ownerId) ?? '') : '',
      ...(isAdmin ? { dealValue: c.dealValue ?? null, retainer: c.retainer ?? null, currency: c.currency ?? 'INR' } : {}),
    }
  })
  return (
    <>
      <AutoRefresh />
      <BoardFilters
        value={filters}
        segments={segments.map((s) => ({ id: s.id, label: s.label }))}
        countries={[...new Set(segments.map((s) => s.country))]}
        team={team.map((m) => ({ id: m.id, name: m.name }))}
        showOwner={user.role !== 'viewer'}
      />
      <Board cards={views} canEdit={canEdit(user.role)} isAdmin={isAdmin} />
    </>
  )
}
