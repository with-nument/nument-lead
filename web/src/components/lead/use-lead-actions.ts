'use client'

import { useTransition } from 'react'
import { toast } from 'sonner'
import { markContacted, markReplied, markWrongContact, skipLead, undoLeadChange, type PreviousState, type UndoKind } from '@/app/(app)/actions'

type Channel = 'web' | 'app' | 'manual' | 'call' | 'email'

/**
 * One-tap lead actions with optimistic UI and an 8-second Undo (plan 15.5.6).
 * `onOptimistic` runs first (for example to hide the row); the server refresh settles the list.
 */
export function useLeadActions(onOptimistic?: (leadId: string) => void) {
  const [pending, startTransition] = useTransition()

  const withUndo = (leadId: string, previous: PreviousState | undefined, kind: UndoKind, text: string) => {
    toast(text, {
      duration: 8000,
      action: previous
        ? {
            label: 'Undo',
            onClick: () => {
              void undoLeadChange(leadId, previous, kind).then((r) => {
                if (r.ok) toast(r.message ?? 'Undone')
                else toast.error(r.message)
              })
            },
          }
        : undefined,
    })
  }

  const run = (leadId: string, fn: () => Promise<{ ok: boolean; message?: string; data?: PreviousState }>, kind: UndoKind, text: string) => {
    startTransition(async () => {
      onOptimistic?.(leadId)
      const r = await fn()
      if (!r.ok) {
        toast.error(r.message ?? 'Could not save. Try again.')
        return
      }
      withUndo(leadId, r.data, kind, text)
    })
  }

  return {
    pending,
    /** Call from the click handler of the link that opens WhatsApp, so the popup is never blocked. */
    markSent: (leadId: string, channel: Channel) => run(leadId, () => markContacted(leadId, channel), 'sent', 'Marked as contacted'),
    /** They answered: Contacted to Talking. */
    replied: (leadId: string) => run(leadId, () => markReplied(leadId), 'replied', 'Marked as replied'),
    skip: (leadId: string) => run(leadId, () => skipLead(leadId), 'skip', 'Skipped for 7 days'),
    wrongContact: (leadId: string) => run(leadId, () => markWrongContact(leadId), 'wrong_contact', 'Marked as wrong contact. The number is now on Do not contact.'),
  }
}
