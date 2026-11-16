'use client'

import Link from 'next/link'
import { Fragment, useMemo, useState } from 'react'
import { ArrowRight, ChevronDown, Ellipsis, Handshake } from 'lucide-react'
import { buttonClass } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { EmptyState } from '@/components/ui2/empty-state'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { STAGE_V2, stageLabel } from '@/components/ui2/stage-label'
import { STAGE_VALUES, type Stage } from '@/lib/stages'
import { Dot, panel, plainClass } from '../../leads/_ui/marks'
import { useStageMove } from '../../leads/_ui/stage-move'
import { UndoRow, useUndo } from '../../leads/_ui/use-run'
import type { BoardView, DealCardView } from './model'

const SHOWN = 5
const MOVE_TO = STAGE_VALUES.filter((s) => s !== 'new')

function StageMenu({ card, onMove }: { card: DealCardView; onMove: (to: Stage) => void }) {
  return (
    <Menu>
      <MenuTrigger
        aria-label={`Move ${card.name}`}
        className="relative z-10 -mr-2 grid size-11 shrink-0 place-items-center rounded-control text-label-3 opacity-100 hover:bg-fill-2 hover:text-label-1 focus-visible:opacity-100 lg:size-8 lg:opacity-0 lg:group-hover:opacity-100 data-[state=open]:opacity-100"
      >
        <Ellipsis aria-hidden className="size-4" />
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>Move to</MenuLabel>
        {MOVE_TO.map((s) => (
          <Fragment key={s}>
            {s === 'won' ? <MenuSeparator /> : null}
            <MenuItem disabled={s === card.stage} onSelect={() => onMove(s)}>
              {STAGE_V2[s].label}
            </MenuItem>
          </Fragment>
        ))}
      </MenuContent>
    </Menu>
  )
}

function Card({ card, canEdit, onMove, onDragStart }: { card: DealCardView; canEdit: boolean; onMove: (to: Stage) => void; onDragStart: () => void }) {
  return (
    <li
      draggable={canEdit}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', card.id)
        onDragStart()
      }}
      className={cx('group relative flex items-start gap-2 px-4 py-4 hairline-t hover:bg-fill-3 lg:px-6', canEdit && 'lg:cursor-grab lg:active:cursor-grabbing')}
    >
      <div className="min-w-0 flex-1">
        <Link href={`/leads/${card.id}`} draggable={false} className="flex items-center gap-2 font-medium text-label-1 outline-none after:absolute after:inset-0 focus-visible:underline lg:text-[16px]">
          {card.dot ? <Dot tone={card.dot} /> : null}
          <span className="truncate">{card.name}</span>
        </Link>
        <p className="mt-1 truncate text-[14px] text-label-2 lg:text-[15px]">{card.line}</p>
        {card.meta ? <p className={cx('mt-1 text-[14px] lg:text-[15px]', card.overdue ? 'text-status-warn' : 'text-label-3')}>{card.overdue ? `Was due ${card.meta}` : card.meta}</p> : null}
      </div>
      {canEdit ? <StageMenu card={card} onMove={onMove} /> : null}
    </li>
  )
}

/** The v2 Deals page: open stages as columns, closed folded underneath, drag (laptop) or the card menu to move. */
export function DealsBoard({ view, canEdit, isAdmin }: { view: BoardView; canEdit: boolean; isAdmin: boolean }) {
  const [mode, setMode] = useState<'columns' | 'list'>('columns')
  const [local, setLocal] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [showClosed, setShowClosed] = useState(false)
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const undo = useUndo()
  const move = useStageMove({ isAdmin, undo, onLocal: (id, s) => setLocal((cur) => ({ ...cur, [id]: s })) })

  const all = useMemo(() => [...view.columns.flatMap((c) => c.cards), ...view.closed.flatMap((c) => c.cards)], [view])
  const stageOf = (c: DealCardView) => local[c.id] ?? c.stage
  const cardsIn = (stage: string) => all.filter((c) => stageOf(c) === stage)
  const countIn = (stage: string, server: number, serverCards: DealCardView[]) => server - serverCards.filter((c) => stageOf(c) !== stage).length + cardsIn(stage).filter((c) => c.stage !== stage).length
  const moveCard = (card: DealCardView, to: Stage) => move.move({ id: card.id, stage: stageOf(card), name: card.name }, to)

  const empty = view.openCount === 0 && view.closed.length === 0

  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-14 lg:pt-11">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 lg:mb-8">
        <div className="min-w-0">
          <h1 className="text-[30px] leading-[1.15] font-semibold tracking-[-0.025em] text-label-1 lg:text-[32px]">Deals</h1>
          <p className="mt-1.5 text-[15px] text-label-3 lg:mt-2">
            {view.openCount} open{view.inPlay ? ` · ${view.inPlay} in proposals and finished calls` : ''}
          </p>
        </div>
        <div className="flex w-full items-center gap-3 lg:w-auto">
          <div role="radiogroup" aria-label="Show as" className="inline-flex gap-0.5 rounded-[12px] bg-fill-2 p-[3px]">
            {(['columns', 'list'] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => setMode(m)}
                className="h-[38px] rounded-[9px] px-4 text-[15px] text-label-3 hover:text-label-1 aria-checked:bg-thumb aria-checked:font-semibold aria-checked:text-label-1 aria-checked:shadow-[var(--ui-shadow-thumb)] lg:h-[38px] lg:text-[14px]"
              >
                {m === 'columns' ? 'Columns' : 'List'}
              </button>
            ))}
          </div>
          {view.primary ? (
            <Link href={view.primary.href} className={buttonClass('primary', 'regular', 'ml-auto min-w-0 lg:h-12 lg:rounded-[14px] lg:px-5 lg:text-[15px]')}>
              <span className="truncate">{view.primary.label}</span>
              <ArrowRight aria-hidden />
            </Link>
          ) : null}
        </div>
      </header>

      <UndoRow undo={undo} className="mb-4" />

      {empty ? (
        <section className={panel}>
          <EmptyState icon={<Handshake />} title="No deals yet">
            A lead becomes a deal once you contact it. Start from Today&rsquo;s send list.
          </EmptyState>
        </section>
      ) : mode === 'columns' ? (
        <section aria-label="Open deals" className={cx(panel, '-mx-4 overflow-x-auto rounded-none sm:mx-0 sm:rounded-panel')}>
          <div className="grid min-w-[1000px] grid-cols-5 lg:min-w-0">
            {view.columns.map((col, i) => {
              const cards = cardsIn(col.stage)
              const shown = expanded[col.stage] ? cards : cards.slice(0, SHOWN)
              const count = countIn(col.stage, col.count, col.cards)
              return (
                <div
                  key={col.stage}
                  onDragOver={(e) => {
                    if (!dragging) return
                    e.preventDefault()
                    setOver(col.stage)
                  }}
                  onDragLeave={() => setOver((o) => (o === col.stage ? null : o))}
                  onDrop={(e) => {
                    e.preventDefault()
                    const card = all.find((c) => c.id === (e.dataTransfer.getData('text/plain') || dragging))
                    setDragging(null)
                    setOver(null)
                    if (card) moveCard(card, col.stage as Stage)
                  }}
                  className={cx('flex min-w-0 flex-col', i < view.columns.length - 1 && 'hairline-r', over === col.stage && 'bg-fill-3')}
                >
                  <div className="flex min-h-[86px] flex-col justify-center px-4 lg:px-6">
                    <h2 className="text-[16px] font-semibold text-label-1">
                      {col.label} <span className="font-normal text-label-3">{count}</span>
                    </h2>
                    {col.total ? <p className="mt-1 text-[14px] text-label-3">{col.total}</p> : null}
                  </div>
                  <ul className="flex flex-col">
                    {shown.map((c) => (
                      <Card key={c.id} card={c} canEdit={canEdit} onMove={(to) => moveCard(c, to)} onDragStart={() => setDragging(c.id)} />
                    ))}
                  </ul>
                  {cards.length > SHOWN || count > cards.length ? (
                    <button
                      type="button"
                      onClick={() => setExpanded((e) => ({ ...e, [col.stage]: !e[col.stage] }))}
                      className="min-h-12 px-4 py-4 text-left text-[15px] text-label-3 hairline-t hover:bg-fill-3 hover:text-label-1 lg:px-6"
                    >
                      {expanded[col.stage] ? 'Show fewer' : `${Math.max(0, count - shown.length)} more`}
                    </button>
                  ) : null}
                  {!cards.length ? <p className="px-4 py-4 text-[14px] text-label-3 hairline-t lg:px-6">None right now</p> : null}
                </div>
              )
            })}
          </div>
        </section>
      ) : (
        <section aria-label="Open deals" className={cx(panel, 'overflow-hidden')}>
          <table className="w-full border-collapse text-left">
            <thead className="hidden lg:table-header-group">
              <tr className="text-[13.5px] text-label-3">
                <th className="py-4 pl-6 font-normal">Company</th>
                <th className="py-4 font-normal">Stage</th>
                <th className="py-4 font-normal">Next step</th>
                <th className="py-4 pr-6 font-normal">When or value</th>
              </tr>
            </thead>
            <tbody>
              {view.columns.flatMap((col) =>
                cardsIn(col.stage).map((c) => (
                  <tr key={c.id} className="relative hairline-t hover:bg-fill-3">
                    <td className="py-4 pl-4 lg:pl-6">
                      <Link href={`/leads/${c.id}`} className="flex items-center gap-2 font-medium text-label-1 after:absolute after:inset-0">
                        {c.dot ? <Dot tone={c.dot} /> : null}
                        {c.name}
                      </Link>
                      <p className="type-subhead text-label-3 lg:hidden">
                        {stageLabel(stageOf(c))} · {c.line}
                      </p>
                    </td>
                    <td className="hidden py-4 text-label-1 lg:table-cell">{stageLabel(stageOf(c))}</td>
                    <td className="hidden py-4 text-label-2 lg:table-cell">{c.line}</td>
                    <td className={cx('hidden py-4 pr-6 lg:table-cell', c.overdue ? 'text-status-warn' : 'text-label-3')}>{c.meta}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </section>
      )}

      {view.closed.length ? (
        <section aria-label="Closed deals" className={cx(panel, 'mt-5 overflow-hidden')}>
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 px-4 py-4 lg:px-[30px] lg:py-6">
            <h2 className="text-[16px] font-semibold text-label-1">Closed</h2>
            {view.closed.map((c) => (
              <span key={c.stage} className="text-[16px] text-label-3">
                {c.label} <span className="font-semibold text-label-1">{c.count}</span>
                {c.total ? <span> · {c.total}</span> : null}
              </span>
            ))}
            <button type="button" aria-expanded={showClosed} onClick={() => setShowClosed((s) => !s)} className={plainClass('small', 'ml-auto')}>
              {showClosed ? 'Hide' : 'Show'}
              <ChevronDown aria-hidden className={cx('transition-transform', showClosed && 'rotate-180')} />
            </button>
          </div>
          {showClosed ? (
            <ul>
              {view.closed.flatMap((col) =>
                cardsIn(col.stage).map((c) => <Card key={c.id} card={{ ...c, line: `${stageLabel(stageOf(c))} · ${c.line}` }} canEdit={canEdit} onMove={(to) => moveCard(c, to)} onDragStart={() => undefined} />),
              )}
            </ul>
          ) : null}
        </section>
      ) : null}
      {canEdit ? <p className="type-caption mt-3 hidden text-label-3 lg:block">Drag a deal to another column, or use its menu to move it.</p> : null}
      {move.dialogs}
    </div>
  )
}
