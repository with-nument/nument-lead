'use client'

import { lazy, Suspense, useState } from 'react'
import { markContacted, markReplied, skipLead, undoLeadChange, type PreviousState, type UndoKind } from '@/app/(app)/actions'
import { Button } from '@/components/ui2/button'
import { EmptyLine } from '@/components/ui2/empty-state'
import { toast } from '@/components/ui2/toast'
import { UndoRow, useUndoQueue } from '@/components/ui2/undo-row'
import type { ActionResult } from '@/lib/action-result'
import { CompanyMark, Note, TodayRow, TodaySection } from './section'
import type { StartupItem } from './types'

// The full list (with its menu) loads when someone opens it.
const StartupsList = lazy(() => import('./startups-list').then((m) => ({ default: m.StartupsList })))

export type StartupsSectionProps = {
  step: number
  items: StartupItem[]
  /** All ready to contact, when `items` is only the first part of the list. */
  total?: number
  primary?: boolean
  canEdit: boolean
  /** One line under the names ("All grade A or B · emails verified"). */
  summary?: string
}

const SHOWN_NAMES = 3

/**
 * Step 5: new startups to contact. One summary row (mockup); "Review" opens the list, where each startup can be
 * marked contacted, marked as replied or skipped. Each change is saved at once and can be undone for 30 seconds.
 */
export function StartupsSection({ step, items, total, primary, canEdit, summary }: StartupsSectionProps) {
  const [open, setOpen] = useState(false)
  const queue = useUndoQueue()
  const waiting = items.filter((s) => !queue.has(s.leadId))
  const count = waiting.length + Math.max(0, (total ?? items.length) - items.length)
  const names = waiting.slice(0, SHOWN_NAMES).map((s) => s.company)
  const more = count - names.length

  function act(s: StartupItem, kind: UndoKind, run: () => Promise<ActionResult<PreviousState>>, message: string) {
    const saved = run()
    queue.push({
      id: s.leadId,
      message,
      // Undo waits for the save, so an early Undo still restores the state from before it.
      undo: async () => {
        const res = await saved
        if (!res.ok || !res.data) return
        const undone = await undoLeadChange(s.leadId, res.data, kind)
        if (!undone.ok) toast.error(undone.message)
      },
    })
    void saved.then((res) => {
      if (!res.ok) {
        toast.error(res.message)
        queue.undo(s.leadId)
      }
    })
  }

  return (
    <TodaySection id="startups" step={step} title="New startups to contact" count={count} collapsibleOnPhone defaultOpen={primary}>
      {queue.items.map((c) => (
        <UndoRow key={c.id} change={c} onUndo={() => queue.undo(c.id)} />
      ))}
      {waiting.length === 0 ? (
        queue.items.length === 0 ? (
          <EmptyLine>No new startups today. The engine looks overnight; new ones that pass every check arrive here by morning.</EmptyLine>
        ) : null
      ) : (
        <TodayRow
          action={
            <Button variant={primary && !open ? 'primary' : 'secondary'} aria-expanded={open} aria-controls="startups-list" onClick={() => setOpen(!open)}>
              {open ? 'Hide the list' : 'Review and start'}
            </Button>
          }
        >
          <span aria-hidden className="flex shrink-0 max-lg:hidden">
            {waiting.slice(0, SHOWN_NAMES).map((s, i) => (
              <CompanyMark key={s.leadId} name={s.company} className={i > 0 ? '-ml-2 shadow-[0_0_0_2px_var(--ui-panel)]' : 'shadow-[0_0_0_2px_var(--ui-panel)]'} />
            ))}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-[550] text-label-1 lg:truncate">
              {names.join(', ')}
              {more > 0 ? <span className="font-normal text-label-3"> and {more} more</span> : null}
            </p>
            {summary ? <Note>{summary}</Note> : null}
          </div>
        </TodayRow>
      )}
      {open ? (
        <Suspense fallback={<div id="startups-list" className="h-[72px] bg-row-done" />}>
          <StartupsList
            items={waiting}
            canEdit={canEdit}
            onAct={(st, kind) =>
              kind === 'sent'
                ? act(st, 'sent', () => markContacted(st.leadId, 'manual'), `${st.company} marked as contacted`)
                : kind === 'replied'
                  ? act(st, 'replied', () => markReplied(st.leadId), `${st.company} marked as replied`)
                  : act(st, 'skip', () => skipLead(st.leadId), `${st.company} skipped for now`)
            }
          />
        </Suspense>
      ) : null}
    </TodaySection>
  )
}
