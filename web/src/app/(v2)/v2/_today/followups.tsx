'use client'

import { markFollowupSent } from '@/app/(app)/actions'
import { Button } from '@/components/ui2/button'
import { EmptyLine } from '@/components/ui2/empty-state'
import { toast } from '@/components/ui2/toast'
import { UndoRow, useUndoQueue } from '@/components/ui2/undo-row'
import { CompanyMark, Note, TodayRow, TodaySection, Who } from './section'
import type { FollowupItem } from './types'

export type FollowupsSectionProps = {
  step: number
  items: FollowupItem[]
  primary?: boolean
  canEdit: boolean
}

/**
 * Step 4: follow-ups due. "Mark sent" shows at once with a 30 second Undo; the follow-up is saved as sent when
 * the Undo runs out or the page is left (markFollowupSent has no undo of its own).
 */
export function FollowupsSection({ step, items, primary, canEdit }: FollowupsSectionProps) {
  const queue = useUndoQueue()
  const key = (f: FollowupItem) => `${f.leadId}:${f.which}`
  const waiting = items.filter((f) => !queue.has(key(f)))
  return (
    <TodaySection id="followups" step={step} title="Follow-ups due" count={waiting.length} collapsibleOnPhone defaultOpen={primary}>
      {queue.items.map((c) => (
        <UndoRow key={c.id} change={c} onUndo={() => queue.undo(c.id)} />
      ))}
      {waiting.length === 0 && queue.items.length === 0 ? (
        <EmptyLine>No follow-ups due. Leads that have not answered come back here on day 3 and day 7.</EmptyLine>
      ) : null}
      {waiting.map((f, i) => (
        <TodayRow
          key={key(f)}
          action={
            canEdit ? (
              <Button
                variant={primary && i === 0 ? 'primary' : 'secondary'}
                onClick={() =>
                  queue.push({
                    id: key(f),
                    message: `Follow-up to ${f.company} marked as sent`,
                    countdown: 'Saving in',
                    commit: async () => {
                      const res = await markFollowupSent({ leadId: f.leadId, which: f.which, channel: 'manual' })
                      if (!res.ok) toast.error(res.message)
                    },
                  })
                }
              >
                Mark sent
              </Button>
            ) : null
          }
        >
          <CompanyMark name={f.company} className="max-lg:hidden" />
          <div className="min-w-0 flex-1">
            <Who main={f.company} sub={f.person} />
            <Note>
              {f.overdue ? <span aria-hidden className="mr-1.5 inline-block size-[7px] rounded-full bg-dot-warn align-middle" /> : null}
              {f.note}
            </Note>
          </div>
        </TodayRow>
      ))}
    </TodaySection>
  )
}
