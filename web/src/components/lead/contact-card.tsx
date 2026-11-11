'use client'

import { Globe, Mail, MapPin, Phone } from 'lucide-react'
import { Tag } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import { CONTACT_SOURCE_LABEL, PHONE_TYPE_LABEL } from '@/lib/signals'
import { ContactButtons } from './contact-actions'
import { useLeadActions } from './use-lead-actions'

export type ContactView = {
  id: string
  name: string | null
  role: string | null
  phone: string | null
  phoneDisplay: string
  phoneType: string
  email: string | null
  source: string
  sourceUrl: string | null
  isDecisionMaker: boolean
  verified: boolean
  blocked: boolean
  blockReason: string | null
}

export function ContactCard({
  leadId,
  contacts,
  message,
  website,
  mapsUrl,
  canEdit,
}: {
  leadId: string
  contacts: ContactView[]
  message: string | null
  website: string | null
  mapsUrl: string | null
  canEdit: boolean
}) {
  const actions = useLeadActions()
  return (
    <Card aria-labelledby="contact-title">
      <CardHeader id="contact-title" title="Contact" />
      <CardBody className="flex flex-col gap-4">
        {contacts.length ? (
          <ul className="flex flex-col divide-y divide-line-2">
            {contacts.map((c) => (
              <li key={c.id} className="py-3 first:pt-0 last:pb-0">
                {c.name ? (
                  <div className="text-base text-tx-1">
                    {c.name}
                    {c.role ? <span className="text-tx-3">, {c.role}</span> : null}
                    {c.isDecisionMaker ? <Tag tone="indigo" className="ml-2 align-[1px]">Decision maker</Tag> : null}
                  </div>
                ) : null}
                {c.phone ? (
                  <div className="mt-1">
                    <div className={cn('flex flex-wrap items-center gap-x-2 text-base', c.blocked && 'text-tx-3 line-through')}>
                      <Phone aria-hidden className="size-3.5 text-tx-3" />
                      <span className="tabular">{c.phoneDisplay}</span>
                      <span className="text-sm text-tx-3 no-underline">
                        {PHONE_TYPE_LABEL[c.phoneType] ?? 'phone'} · {CONTACT_SOURCE_LABEL[c.source] ?? c.source}
                        {c.verified ? ' · verified' : ''}
                      </span>
                    </div>
                    {c.blocked ? (
                      <p className="mt-1 text-sm text-bad">Do not contact{c.blockReason ? `: ${c.blockReason}` : ''}</p>
                    ) : canEdit ? (
                      <ContactButtons
                        className="mt-2"
                        target={{ phone: c.phone, phoneType: c.phoneType, message }}
                        onOpen={(channel) => actions.markSent(leadId, channel)}
                      />
                    ) : null}
                  </div>
                ) : null}
                {c.email ? (
                  <a href={`mailto:${c.email}`} className="mt-1 flex items-center gap-2 text-base text-indigo-800 hover:text-indigo-900">
                    <Mail aria-hidden className="size-3.5" />
                    {c.email}
                  </a>
                ) : null}
                {c.sourceUrl ? (
                  <a href={c.sourceUrl} target="_blank" rel="noopener noreferrer" className="mt-1 block text-xs text-tx-3 hover:text-indigo-800">
                    Where we found it
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-base text-tx-3">No published phone or email yet.</p>
        )}
        {website || mapsUrl ? (
          <div className="flex flex-col gap-1.5 border-t border-line-2 pt-3">
            {website ? (
              <a href={website} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 text-base text-indigo-800 hover:text-indigo-900">
                <Globe aria-hidden className="size-3.5" />
                Website
              </a>
            ) : null}
            {mapsUrl ? (
              <a href={mapsUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 text-base text-indigo-800 hover:text-indigo-900">
                <MapPin aria-hidden className="size-3.5" />
                Google listing
              </a>
            ) : null}
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}
