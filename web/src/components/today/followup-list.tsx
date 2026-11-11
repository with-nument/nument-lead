'use client'

import Link from 'next/link'
import { useTransition } from 'react'
import { toast } from 'sonner'
import { StageBadge, Tag } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { ContactButtons } from '@/components/lead/contact-actions'
import { markFollowupSent } from '@/app/(app)/actions'

export type FollowupItem = {
  id: string
  name: string
  city: string | null
  stage: string
  nextStep: string | null
  dueLabel: string
  overdue: boolean
  phone: string | null
  phoneType: string | null
  /** The follow-up text to send now, if one is due. */
  followup: { which: 'd3' | 'd7'; text: string } | null
}

export function FollowupList({ items, canEdit }: { items: FollowupItem[]; canEdit: boolean }) {
  const [, startTransition] = useTransition()
  if (!items.length) return <EmptyState text="No follow-ups due today." />
  return (
    <ul className="divide-y divide-line-2">
      {items.map((f) => (
        <li key={f.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-5">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/leads/${f.id}`} className="truncate font-medium text-tx-1 hover:text-indigo-800">
                {f.name}
              </Link>
              <StageBadge stage={f.stage} />
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-tx-3">
              <span className="text-tx-2">{f.nextStep || 'Next step'}</span>
              <span className="text-tx-4">·</span>
              {f.overdue ? <Tag tone="bad">Overdue, {f.dueLabel}</Tag> : <span>Due {f.dueLabel}</span>}
              {f.city ? (
                <>
                  <span className="text-tx-4">·</span>
                  <span>{f.city}</span>
                </>
              ) : null}
            </div>
          </div>
          {canEdit ? (
            <ContactButtons
              target={{ phone: f.phone, phoneType: f.phoneType, message: f.followup?.text ?? '' }}
              onOpen={(channel) => {
                const followup = f.followup
                if (!followup) return
                startTransition(async () => {
                  const r = await markFollowupSent({ leadId: f.id, which: followup.which, channel })
                  if (r.ok) toast(r.message ?? 'Saved')
                  else toast.error(r.message)
                })
              }}
            />
          ) : null}
        </li>
      ))}
    </ul>
  )
}
