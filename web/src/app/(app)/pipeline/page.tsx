import type { Metadata } from 'next'
import { Suspense } from 'react'
import { BoardFilters } from '@/components/pipeline/board-filters'
import { Board, type CardView } from '@/components/pipeline/board'
import { AutoRefresh } from '@/components/shell/auto-refresh'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { requireUser } from '@/lib/auth'
import { dueState, formatDate, istDate } from '@/lib/dates'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { getBoard } from '@/lib/queries/pipeline'
import { getSegments, getTeam } from '@/lib/queries/shared'

export const metadata: Metadata = { title: 'Pipeline' }

const UUID = /^[0-9a-f-]{36}$/i

export default function PipelinePage({ searchParams }: PageProps<'/pipeline'>) {
  return (
    <>
      <PageHeader title="Pipeline" description="Every lead after the first message. Drag a card to change its stage." />
      <Suspense fallback={<BoardSkeleton />}>
        <Pipeline searchParams={searchParams} />
      </Suspense>
    </>
  )
}

async function Pipeline({ searchParams }: Pick<PageProps<'/pipeline'>, 'searchParams'>) {
  const [user, sp] = await Promise.all([requireUser(), searchParams])
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
  const isAdmin = canSeeMoney(user.role)
  const [cards, segments, team] = await Promise.all([getBoard(filters, { userId: user.id, today, withMoney: isAdmin }), getSegments(), getTeam()])
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
      ...(isAdmin ? { dealValue: c.dealValue ?? null } : {}),
    }
  })
  return (
    <>
      <AutoRefresh seconds={60} />
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

function BoardSkeleton() {
  return (
    <div className="flex gap-3 overflow-hidden" aria-busy>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="w-72 shrink-0 rounded-2xl border border-line-2 bg-surface-2/60 p-3">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="mt-3 h-16 w-full rounded-xl" />
          <Skeleton className="mt-2 h-16 w-full rounded-xl" />
        </div>
      ))}
    </div>
  )
}
