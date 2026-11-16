'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Ellipsis } from 'lucide-react'
import { markContacted, markReplied, skipLead, undoLeadChange, type PreviousState, type UndoKind } from '@/app/(app)/actions'
import { Button } from '@/components/ui2/button'
import { EmptyLine } from '@/components/ui2/empty-state'
import { GradeMark } from '@/components/ui2/grade-mark'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui2/menu'
import { toast } from '@/components/ui2/toast'
import { UndoRow, useUndoQueue } from '@/components/ui2/undo-row'
import type { ActionResult } from '@/lib/action-result'
import { CompanyMark, Note, TodayRow, TodaySection, Who } from './section'
import type { StartupItem } from './types'

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
        <div id="startups-list" className="[&>*+*]:hairline-t">
          {waiting.map((s) => (
            <TodayRow
              key={s.leadId}
              className="bg-row-done"
              action={
                canEdit ? (
                  <>
                    <Button onClick={() => act(s, 'sent', () => markContacted(s.leadId, 'manual'), `${s.company} marked as contacted`)}>Mark contacted</Button>
                    <Menu>
                      <MenuTrigger aria-label={`More for ${s.company}`} className="grid size-11 shrink-0 place-items-center rounded-control text-label-2 hover:bg-fill-3 max-lg:!flex-none lg:size-[38px]">
                        <Ellipsis aria-hidden className="size-[18px]" strokeWidth={1.6} />
                      </MenuTrigger>
                      <MenuContent>
                        <MenuItem onSelect={() => act(s, 'replied', () => markReplied(s.leadId), `${s.company} marked as replied`)}>They replied</MenuItem>
                        <MenuItem onSelect={() => act(s, 'skip', () => skipLead(s.leadId), `${s.company} skipped for now`)}>Skip for now</MenuItem>
                        <MenuItem asChild>
                          <Link href={`/leads/${s.leadId}`}>Open the lead</Link>
                        </MenuItem>
                      </MenuContent>
                    </Menu>
                  </>
                ) : (
                  <Link href={`/leads/${s.leadId}`} className="text-[14px] text-label-1 underline decoration-separator-strong underline-offset-[3px]">
                    Open
                  </Link>
                )
              }
            >
              <GradeMark grade={s.grade} />
              <div className="min-w-0 flex-1">
                <Who main={s.company} sub={[s.person, s.city].filter(Boolean).join(', ') || null} />
                {s.signal ? <Note>{s.signal}</Note> : null}
              </div>
            </TodayRow>
          ))}
        </div>
      ) : null}
    </TodaySection>
  )
}
