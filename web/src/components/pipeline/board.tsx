'use client'

import Link from 'next/link'
import { useMemo, useOptimistic, useState, useTransition } from 'react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
  type KeyboardCoordinateGetter,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { toast } from 'sonner'
import { setDealValue, updateStage } from '@/app/(app)/leads/[id]/actions'
import { GradeBadge, Tag } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { formatInr, initials } from '@/lib/format'
import { BOARD_STAGES, WON_STAGES, stageOf, type Stage } from '@/lib/stages'

export type CardView = {
  id: string
  name: string
  city: string | null
  grade: string | null
  stage: string
  nextStep: string | null
  due: string
  overdue: boolean
  owner: string
  dealValue?: number | null
}

const collision: CollisionDetection = (args) => {
  const hits = pointerWithin(args)
  return hits.length ? hits : rectIntersection(args)
}

/** Arrow keys move a picked-up card one column left or right (dnd-kit KeyboardSensor). */
const columnKeys: KeyboardCoordinateGetter = (event, { context }) => {
  const { collisionRect, droppableRects, droppableContainers } = context
  if (!collisionRect || (event.code !== 'ArrowRight' && event.code !== 'ArrowLeft')) return undefined
  event.preventDefault()
  const columns = droppableContainers
    .getEnabled()
    .map((c) => ({ id: c.id, rect: droppableRects.get(c.id) }))
    .filter((c): c is { id: string | number; rect: NonNullable<typeof c.rect> } => Boolean(c.rect))
    .sort((a, b) => a.rect.left - b.rect.left)
  const center = collisionRect.left + collisionRect.width / 2
  let index = columns.findIndex((c) => center >= c.rect.left && center <= c.rect.left + c.rect.width)
  if (index < 0) index = 0
  const next = columns[Math.max(0, Math.min(columns.length - 1, index + (event.code === 'ArrowRight' ? 1 : -1)))]
  if (!next) return undefined
  return { x: next.rect.left + (next.rect.width - collisionRect.width) / 2, y: next.rect.top + 48 }
}

export function Board({ cards, canEdit, isAdmin }: { cards: CardView[]; canEdit: boolean; isAdmin: boolean }) {
  const [items, move] = useOptimistic(cards, (state, m: { id: string; stage: string }) => state.map((c) => (c.id === m.id ? { ...c, stage: m.stage } : c)))
  const [, startTransition] = useTransition()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [dealFor, setDealFor] = useState<{ id: string; name: string } | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: columnKeys }),
  )
  const byStage = useMemo(() => {
    const m = new Map<string, CardView[]>()
    for (const s of BOARD_STAGES) m.set(s.value, [])
    for (const c of items) m.get(c.stage)?.push(c)
    return m
  }, [items])
  const active = activeId ? items.find((c) => c.id === activeId) : null

  const onDragEnd = (e: DragEndEvent) => {
    setActiveId(null)
    const stage = e.over?.id ? String(e.over.id) : null
    const id = String(e.active.id)
    const card = items.find((c) => c.id === id)
    if (!stage || !card || card.stage === stage) return
    startTransition(async () => {
      move({ id, stage })
      const r = await updateStage({ leadId: id, stage: stage as Stage })
      if (!r.ok) {
        toast.error(r.message)
        return
      }
      toast(`${card.name} moved to ${stageOf(stage).label}`)
      if (isAdmin && WON_STAGES.includes(stage as Stage)) setDealFor({ id, name: card.name })
    })
  }

  const columns = (
    <div className="flex gap-3 overflow-x-auto pb-4" role="list" aria-label="Pipeline stages">
      {BOARD_STAGES.map((s) => (
        <Column key={s.value} stage={s.value} label={s.label} closed={s.closed} cards={byStage.get(s.value) ?? []} canEdit={canEdit} isAdmin={isAdmin} />
      ))}
    </div>
  )

  return (
    <>
      {canEdit ? (
        <DndContext
          id="pipeline-board"
          sensors={sensors}
          collisionDetection={collision}
          onDragStart={(e: DragStartEvent) => setActiveId(String(e.active.id))}
          onDragCancel={() => setActiveId(null)}
          onDragEnd={onDragEnd}
          accessibility={{
            screenReaderInstructions: {
              draggable: 'To move a lead, press space or enter, use the left and right arrow keys to choose a stage, then press space or enter again. Press escape to cancel.',
            },
            announcements: {
              onDragStart: ({ active: a }) => `Picked up ${items.find((c) => c.id === a.id)?.name ?? 'lead'}.`,
              onDragOver: ({ over }) => (over ? `Over ${stageOf(String(over.id)).label}.` : 'Not over a stage.'),
              onDragEnd: ({ over }) => (over ? `Moved to ${stageOf(String(over.id)).label}.` : 'Dropped. No change.'),
              onDragCancel: () => 'Cancelled. No change.',
            },
          }}
        >
          {columns}
          <DragOverlay>{active ? <CardBody card={active} isAdmin={isAdmin} dragging /> : null}</DragOverlay>
        </DndContext>
      ) : (
        columns
      )}
      <DealDialog lead={dealFor} onClose={() => setDealFor(null)} />
    </>
  )
}

function Column({ stage, label, closed, cards, canEdit, isAdmin }: { stage: string; label: string; closed: boolean; cards: CardView[]; canEdit: boolean; isAdmin: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: stage, disabled: !canEdit })
  const s = stageOf(stage)
  return (
    <section
      ref={setNodeRef}
      role="listitem"
      aria-label={`${label}, ${cards.length} ${cards.length === 1 ? 'lead' : 'leads'}`}
      className={cn(
        'flex max-h-[calc(100dvh-220px)] min-h-48 shrink-0 flex-col rounded-2xl border bg-surface-2/60 transition-colors',
        closed ? 'w-52' : 'w-72',
        isOver ? 'border-indigo-300 bg-indigo-50' : 'border-line-2',
      )}
    >
      <header className="flex items-center justify-between gap-2 px-3 pt-3 pb-2">
        <span className="inline-flex h-6 items-center rounded-[6px] px-2 text-xs font-medium" style={{ background: s.bg, color: s.fg }}>
          {label}
        </span>
        <span className="tabular text-sm text-tx-3">{cards.length}</span>
      </header>
      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
        {cards.map((c) => (
          <DraggableCard key={c.id} card={c} canEdit={canEdit} isAdmin={isAdmin} compact={closed} />
        ))}
        {!cards.length ? <li className="px-2 py-6 text-center text-sm text-tx-4">{canEdit ? 'Drop leads here' : 'Empty'}</li> : null}
      </ul>
    </section>
  )
}

function DraggableCard({ card, canEdit, isAdmin, compact }: { card: CardView; canEdit: boolean; isAdmin: boolean; compact: boolean }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: card.id, disabled: !canEdit })
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform) }}
      className={cn('rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-indigo-400', isDragging && 'opacity-40')}
      {...(canEdit ? { ...attributes, ...listeners } : {})}
      aria-roledescription={canEdit ? 'Draggable lead' : undefined}
    >
      <CardBody card={card} isAdmin={isAdmin} compact={compact} draggable={canEdit} />
    </li>
  )
}

function CardBody({ card, isAdmin, compact, dragging, draggable }: { card: CardView; isAdmin: boolean; compact?: boolean; dragging?: boolean; draggable?: boolean }) {
  return (
    <div className={cn('rounded-xl border border-line-2 bg-surface p-3 select-none', draggable && 'cursor-grab active:cursor-grabbing', dragging && 'shadow-menu rotate-1 cursor-grabbing')}>
      <div className="flex items-start gap-2">
        <GradeBadge grade={card.grade} />
        <div className="min-w-0 flex-1">
          <Link href={`/leads/${card.id}`} className="block truncate text-base font-medium text-tx-1 hover:text-indigo-800" onPointerDown={(e) => e.stopPropagation()}>
            {card.name}
          </Link>
          {!compact && card.city ? <div className="truncate text-xs text-tx-3">{card.city}</div> : null}
        </div>
        {card.owner ? (
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-indigo-100 text-micro font-medium text-indigo-800" title={card.owner}>
            {initials(card.owner)}
          </span>
        ) : null}
      </div>
      {!compact && (card.nextStep || card.due) ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          {card.nextStep ? <span className="text-tx-2">{card.nextStep}</span> : null}
          {card.due ? card.overdue ? <Tag tone="bad" className="h-5 px-1.5">Overdue, {card.due}</Tag> : <span className="text-tx-3">{card.due}</span> : null}
        </div>
      ) : null}
      {isAdmin && card.dealValue ? <div className="mt-1.5 text-xs text-green-800 tabular">{formatInr(card.dealValue)}</div> : null}
    </div>
  )
}

function DealDialog({ lead, onClose }: { lead: { id: string; name: string } | null; onClose: () => void }) {
  const [amount, setAmount] = useState('')
  const [pending, start] = useTransition()
  return (
    <Dialog open={Boolean(lead)} onOpenChange={(o) => !o && onClose()}>
      {lead ? (
        <DialogContent title={`Deal value for ${lead.name}`} description="Only admins see this. You can change it later on the lead page.">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              start(async () => {
                const r = await setDealValue({ leadId: lead.id, value: amount })
                if (r.ok) {
                  toast(r.message ?? 'Saved')
                  setAmount('')
                  onClose()
                } else toast.error(r.message)
              })
            }}
          >
            <Field label="Amount (₹)">
              {({ id }) => <Input id={id} inputMode="decimal" autoFocus value={amount} onChange={(e) => setAmount(e.currentTarget.value.replace(/[^\d.]/g, ''))} placeholder="150000" />}
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                Later
              </Button>
              <Button type="submit" variant="primary" loading={pending} disabled={!amount}>
                Save
              </Button>
            </div>
          </form>
        </DialogContent>
      ) : null}
    </Dialog>
  )
}
