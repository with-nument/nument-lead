'use client'

import Link from 'next/link'
import { buttonClass } from '@/components/ui2/button'
import { EmptyLine } from '@/components/ui2/empty-state'
import { UndoRow, useUndoQueue } from '@/components/ui2/undo-row'
import { toast } from '@/components/ui2/toast'
import { Button } from '@/components/ui2/button'
import { PersonMark, TodayRow, TodaySection } from './section'
import type { ReplyItem, TodayActionResult } from './types'

export type RepliesSectionProps = {
  step: number
  items: ReplyItem[]
  /** This section holds the page's one solid button. */
  primary?: boolean
  canEdit: boolean
  /**
   * Sends the approved answer. Called when the 30 second Undo runs out (or the page is left), so Undo never
   * has to unsend an email. Without it the button opens the lead, where the answer can be read first.
   */
  approve?: (replyId: string) => Promise<TodayActionResult>
}

/** Step 1: replies from founders, each with a drafted answer to approve. */
export function RepliesSection({ step, items, primary, canEdit, approve }: RepliesSectionProps) {
  const queue = useUndoQueue()
  const waiting = items.filter((r) => !queue.has(r.id))
  return (
    <TodaySection id="replies" step={step} title="Replies to approve" count={waiting.length} countLabel={queue.items.length ? `${waiting.length} left` : undefined} collapsibleOnPhone={items.length === 0} defaultOpen={primary}>
      {queue.items.map((c) => (
        <UndoRow key={c.id} change={c} onUndo={() => queue.undo(c.id)} />
      ))}
      {waiting.length === 0 && queue.items.length === 0 ? (
        <EmptyLine>No replies waiting. When a founder answers, their message and a suggested reply appear here.</EmptyLine>
      ) : null}
      {waiting.map((r, i) => {
        const solid = primary && i === 0
        const action =
          approve && canEdit ? (
            <Button
              variant={solid ? 'primary' : 'secondary'}
              onClick={() =>
                queue.push({
                  id: r.id,
                  message: `Reply sent to ${r.person} at ${r.company}`,
                  countdown: 'Sending in',
                  commit: async () => {
                    const res = await approve(r.id)
                    if (!res.ok) toast.error(res.message)
                  },
                })
              }
            >
              Approve and send
            </Button>
          ) : (
            <Link href={`/leads/${r.leadId}`} className={buttonClass(solid ? 'primary' : 'secondary')}>
              Read and reply
            </Link>
          )
        return (
          <TodayRow key={r.id} action={action}>
            <PersonMark name={r.person} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[15px] font-[550] text-label-1">
                {r.person} <span className="font-normal text-label-3">· {r.company}</span>
              </p>
              <p className="mt-0.5 text-[14.5px] text-label-1 lg:truncate">“{r.quote}”</p>
              {r.suggestion ? (
                <p className="mt-1 truncate text-[13px] text-label-3">
                  <span className="font-medium text-label-2">Suggested reply</span> · {r.suggestion}
                </p>
              ) : null}
            </div>
          </TodayRow>
        )
      })}
    </TodaySection>
  )
}
