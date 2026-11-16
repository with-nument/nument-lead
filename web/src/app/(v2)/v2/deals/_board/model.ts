// The v2 Deals board's view of deals_board. Pure, unit tested (tests/unit/lead-v2-model.test.ts).
import { stageLabel } from '@/components/ui2/stage-label'
import { dueState, formatDate, istDate, relativeAge } from '@/lib/dates'
import { formatInr } from '@/lib/format'
import { formatMoney } from '@/lib/outcomes'
import type { Board, BoardCard } from '@/lib/queries/page-data'
import type { DotTone } from '../../leads/_ui/marks'

/** Open stages, one column each (New lives on Today and in Leads). */
export const OPEN_COLUMNS = ['contacted', 'talking', 'discovery_booked', 'discovery_done', 'proposal_sent'] as const
/** Closed stages, folded under the columns with their counts. */
export const CLOSED = ['won', 'retainer', 'lost', 'not_now', 'not_a_fit', 'wrong_contact'] as const

export type DealCardView = {
  id: string
  name: string
  stage: string
  line: string
  meta: string
  dot: DotTone | null
  value: number | null
  overdue: boolean
}

export type DealColumn = { stage: string; label: string; count: number; total: string | null; cards: DealCardView[] }

export type BoardView = {
  columns: DealColumn[]
  closed: { stage: string; label: string; count: number; total: string | null; cards: DealCardView[] }[]
  openCount: number
  /** Admins only: the money in finished calls and proposals out. */
  inPlay: string | null
  primary: { label: string; href: string } | null
}

export function toCardView(c: BoardCard, now: Date): DealCardView {
  const today = istDate(now)
  const state = dueState(c.dueAt, today)
  const money = c.dealValue != null ? formatInr(c.dealValue) : c.retainer != null ? `${formatMoney(c.retainer, c.currency)} a month` : null
  const when = c.dueAt ? (state === 'today' ? 'Today' : formatDate(c.dueAt, now)) : c.lastActivityAt ? relativeAge(c.lastActivityAt, now) : ''
  const needsYou = c.stage === 'talking' || c.stage === 'discovery_done'
  return {
    id: c.id,
    name: c.name,
    stage: c.stage,
    line: c.nextStep ?? (c.city ? c.city : stageLabel(c.stage)),
    meta: money ? (state === 'overdue' && c.dueAt ? `${money} · was due ${formatDate(c.dueAt, now)}` : money) : state === 'overdue' && c.dueAt ? `Was due ${formatDate(c.dueAt, now)}` : when,
    dot: state === 'overdue' ? 'warn' : needsYou ? 'ink' : null,
    value: c.dealValue ?? null,
    overdue: state === 'overdue',
  }
}

const sum = (cards: DealCardView[]) => cards.reduce((s, c) => s + (c.value ?? 0), 0)

export function toBoardView(board: Board, opts: { now: Date; isAdmin: boolean }): BoardView {
  const cards = board.cards.map((c) => toCardView(c, opts.now))
  const by = (stage: string) => cards.filter((c) => c.stage === stage)
  const money = (list: DealCardView[]) => (opts.isAdmin && list.some((c) => c.value != null) ? formatInr(sum(list)) : null)
  const columns = OPEN_COLUMNS.map((stage) => {
    const list = by(stage)
    return { stage, label: stageLabel(stage), count: board.counts[stage] ?? list.length, total: stage === 'discovery_done' || stage === 'proposal_sent' ? money(list) : null, cards: list }
  })
  const closed = CLOSED.map((stage) => {
    const list = by(stage)
    return { stage, label: stageLabel(stage), count: board.counts[stage] ?? list.length, total: stage === 'won' || stage === 'retainer' ? money(list) : null, cards: list }
  }).filter((c) => c.count > 0)
  const late = [...by('discovery_done'), ...by('proposal_sent')]
  const proposal = by('discovery_done')[0]
  const replied = by('talking')[0]
  return {
    columns,
    closed,
    openCount: columns.reduce((s, c) => s + c.count, 0),
    inPlay: opts.isAdmin && late.some((c) => c.value != null) ? formatInr(sum(late)) : null,
    primary: proposal
      ? { label: `Send ${proposal.name} proposal`, href: `/leads/${proposal.id}?tab=activity` }
      : replied
        ? { label: `Answer ${replied.name}`, href: `/leads/${replied.id}?tab=conversation` }
        : null,
  }
}
