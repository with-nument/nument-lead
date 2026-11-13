'use client'

import Link from 'next/link'
import { useOptimistic, useState, useTransition } from 'react'
import { Check, MessageCircleReply } from 'lucide-react'
import { toast } from 'sonner'
import { GradeBadge, Tag } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { ContactButtons } from '@/components/lead/contact-actions'
import { useLeadActions } from '@/components/lead/use-lead-actions'
import { markFollowupSent } from '@/app/(app)/actions'

export type FollowupItem = {
  id: string
  name: string
  city: string | null
  grade: string | null
  which: 'd3' | 'd7'
  text: string
  contactName: string | null
  dueLabel: string
  overdue: boolean
  phone: string | null
  phoneType: string | null
}

const LABEL = { d3: 'Day 3 follow-up', d7: 'Day 7 follow-up' } as const

export function FollowupList({ items, canEdit }: { items: FollowupItem[]; canEdit: boolean }) {
  // A key hides one follow-up; a lead id (Replied) hides every follow-up of that lead.
  const [visible, hide] = useOptimistic(items, (state, key: string) => state.filter((i) => `${i.id}:${i.which}` !== key && i.id !== key))
  const [, startTransition] = useTransition()
  const actions = useLeadActions(hide)

  const send = (f: FollowupItem, channel: 'web' | 'app' | 'call' | 'email' | 'manual') => {
    startTransition(async () => {
      hide(`${f.id}:${f.which}`)
      const r = await markFollowupSent({ leadId: f.id, which: f.which, channel })
      if (r.ok) toast(r.message ?? 'Saved')
      else toast.error(r.message)
    })
  }

  if (!visible.length) return <EmptyState text="No follow-ups due today." />
  return (
    <ul className="divide-y divide-line-2">
      {visible.map((f) => (
        <FollowupRow key={`${f.id}:${f.which}`} f={f} canEdit={canEdit} onSend={(channel) => send(f, channel)} onReplied={() => actions.replied(f.id)} />
      ))}
    </ul>
  )
}

function FollowupRow({
  f,
  canEdit,
  onSend,
  onReplied,
}: {
  f: FollowupItem
  canEdit: boolean
  onSend: (c: 'web' | 'app' | 'call' | 'email' | 'manual') => void
  onReplied: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <li className="grid gap-x-6 gap-y-3 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="flex items-start gap-3">
          <GradeBadge grade={f.grade} className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <Link href={`/leads/${f.id}`} className="truncate text-md font-medium text-tx-1 hover:text-indigo-800">
                {f.name}
              </Link>
              {f.city ? <span className="text-sm text-tx-3">{f.city}</span> : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-tx-2">
              <span>{LABEL[f.which]}</span>
              <span aria-hidden className="text-tx-3">·</span>
              {f.overdue ? <Tag tone="bad">Overdue, due {f.dueLabel}</Tag> : <span className="text-tx-3">Due {f.dueLabel}</span>}
              {f.contactName ? (
                <>
                  <span aria-hidden className="text-tx-3">·</span>
                  <span className="text-tx-3">{f.contactName}</span>
                </>
              ) : null}
            </div>
          </div>
        </div>
        {f.text ? (
          <div className="mt-3 sm:ml-9">
            <p className="rounded-xl bg-surface-2 px-3.5 py-2.5 text-base leading-6 whitespace-pre-line text-tx-2">
              {open || f.text.length <= 120 ? f.text : `${f.text.slice(0, 120).trimEnd()}…`}
            </p>
            {f.text.length > 120 ? (
              <button type="button" onClick={() => setOpen((v) => !v)} className="mt-1 text-sm text-tx-3 hover:text-indigo-800" aria-expanded={open}>
                {open ? 'Show less' : 'Show full message'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {canEdit ? (
        <div className="flex flex-wrap items-start gap-2 sm:ml-9 lg:ml-0 lg:justify-end">
          <ContactButtons target={{ phone: f.phone, phoneType: f.phoneType, message: f.text }} onOpen={onSend} className="max-sm:w-full" />
          <Button size="sm" variant="ghost" onClick={() => onSend('manual')}>
            <Check aria-hidden />
            Mark sent
          </Button>
          <Button size="sm" variant="ghost" onClick={onReplied} title="They answered: move to Talking, no follow-up needed">
            <MessageCircleReply aria-hidden />
            Replied
          </Button>
        </div>
      ) : null}
    </li>
  )
}
