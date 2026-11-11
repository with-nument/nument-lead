'use client'

import Link from 'next/link'
import { useOptimistic, useState } from 'react'
import { Ban, Check, Ellipsis, ExternalLink, SkipForward } from 'lucide-react'
import { GradeBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { ContactButtons } from '@/components/lead/contact-actions'
import { useLeadActions } from '@/components/lead/use-lead-actions'

export type SendItem = {
  id: string
  name: string
  city: string | null
  segment: string
  grade: string | null
  signal: { label: string; age: string; url: string | null; quote: string | null } | null
  contactName: string | null
  contactRole: string | null
  phone: string | null
  phoneDisplay: string
  phoneType: string | null
  phoneMeta: string
  email: string | null
  message: string | null
}

export function SendList({ items, canEdit }: { items: SendItem[]; canEdit: boolean }) {
  const [visible, hide] = useOptimistic(items, (state, id: string) => state.filter((i) => i.id !== id))
  const actions = useLeadActions(hide)

  if (!visible.length) {
    return <EmptyState text="Nothing new to send today. The engine adds leads every morning by 7:30 am." />
  }
  return (
    <ul className="divide-y divide-line-2">
      {visible.map((item) => (
        <SendRow key={item.id} item={item} canEdit={canEdit} actions={actions} />
      ))}
    </ul>
  )
}

function SendRow({ item, canEdit, actions }: { item: SendItem; canEdit: boolean; actions: ReturnType<typeof useLeadActions> }) {
  const [open, setOpen] = useState(false)
  const message = item.message ?? ''
  const long = message.length > 120
  const shown = open || !long ? message : `${message.slice(0, 120).trimEnd()}…`

  return (
    <li className="grid gap-x-6 gap-y-3 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="flex items-start gap-3">
          <GradeBadge grade={item.grade} className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <Link href={`/leads/${item.id}`} className="truncate text-md font-medium text-tx-1 hover:text-indigo-800">
                {item.name}
              </Link>
              <span className="text-sm text-tx-3">{item.city}</span>
              <span className="label-mono">{item.segment}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-sm text-tx-2">
              {item.signal ? (
                <>
                  <span>{item.signal.label}</span>
                  <span className="text-tx-4">·</span>
                  <span className="text-tx-3">{item.signal.age}</span>
                  {item.signal.url ? (
                    <a
                      href={item.signal.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center text-indigo-800 hover:text-indigo-900"
                      title={item.signal.quote ?? 'Open the evidence'}
                    >
                      <ExternalLink className="size-3.5" aria-hidden />
                      <span className="sr-only">Open the evidence</span>
                    </a>
                  ) : null}
                </>
              ) : (
                <span className="text-tx-3">Good fit, no fresh signal</span>
              )}
            </div>
            <div className="mt-1 text-sm text-tx-3">
              {[item.contactName && `${item.contactName}${item.contactRole ? `, ${item.contactRole}` : ''}`, item.phoneDisplay, item.phoneMeta]
                .filter(Boolean)
                .join(' · ') || 'No contact details yet'}
            </div>
          </div>
        </div>
        {message ? (
          <div className="mt-3 sm:ml-9">
            <p className="rounded-xl bg-surface-2 px-3.5 py-2.5 text-base leading-6 whitespace-pre-line text-tx-2">{shown}</p>
            {long ? (
              <button type="button" onClick={() => setOpen((v) => !v)} className="mt-1 text-sm text-tx-3 hover:text-indigo-800" aria-expanded={open}>
                {open ? 'Show less' : 'Show full message'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {canEdit ? (
        <div className="flex flex-wrap items-start gap-2 sm:ml-9 lg:ml-0 lg:max-w-[340px] lg:justify-end">
          <ContactButtons
            target={{ phone: item.phone, phoneType: item.phoneType, message: item.message, email: item.email }}
            onOpen={(channel) => actions.markSent(item.id, channel)}
            className="max-sm:w-full"
          />
          {message ? <CopyButton text={message} size="sm" variant="ghost" label="Copy" /> : null}
          <Menu>
            <MenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label={`More actions for ${item.name}`}>
                <Ellipsis />
              </Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => actions.markSent(item.id, 'manual')}>
                <Check aria-hidden />
                Mark sent
              </MenuItem>
              <MenuItem onSelect={() => actions.skip(item.id)}>
                <SkipForward aria-hidden />
                Skip for 7 days
              </MenuItem>
              <MenuSeparator />
              <MenuItem danger onSelect={() => actions.wrongContact(item.id)}>
                <Ban aria-hidden />
                Wrong contact
              </MenuItem>
            </MenuContent>
          </Menu>
        </div>
      ) : null}
    </li>
  )
}
