'use client'

import { useId, useState } from 'react'
import { ExternalLink, Globe, MapPin } from 'lucide-react'
import { updateOwner } from '@/app/(app)/leads/[id]/actions'
import { cx } from '@/components/ui2/cx'
import { Select } from '@/components/ui2/select'
import { WhoAnswers } from '@/components/ui2/who-answers'
import { eyebrow, panel, plainClass, Status } from '../../_ui/marks'
import { useRun } from '../../_ui/use-run'
import { ContactButtons, type Channel } from './contact-buttons'
import type { LeadView, PersonView } from './model'

function Person({
  p,
  message,
  canEdit,
  onOpen,
  onWrong,
}: {
  p: PersonView
  message: string
  canEdit: boolean
  onOpen: (channel: Channel) => void
  onWrong: () => void
}) {
  return (
    <li className="px-5 py-5 lg:px-[26px] [&+&]:hairline-t">
      <div className="flex items-center gap-3">
        <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-fill-2 text-[12.5px] font-semibold text-label-2 hairline-ring">
          {p.initials}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-label-1">{p.name ?? 'Name not published'}</p>
          <p className="type-subhead truncate text-label-3">{[p.role, p.isDecisionMaker ? 'Decision maker' : null].filter(Boolean).join(' · ') || 'Role not published'}</p>
        </div>
      </div>
      <dl className="mt-3 flex flex-col gap-2 pl-12">
        {p.email ? (
          <div>
            <dt className="sr-only">Email</dt>
            <dd>
              <a href={`mailto:${p.email}`} className="text-label-1 underline decoration-separator-strong underline-offset-4">
                {p.email}
              </a>
              <span className="type-subhead mt-0.5 block text-label-2">
                {p.verified ? <Status tone="ok">Verified{p.verifiedOn ? ` on ${p.verifiedOn}` : ''}</Status> : <Status tone="warn">Not verified yet</Status>}
              </span>
            </dd>
          </div>
        ) : null}
        {p.phone ? (
          <div>
            <dt className="sr-only">Phone</dt>
            <dd>
              <span className={cx('text-label-1', p.blocked && 'text-label-3 line-through')}>{p.phoneDisplay}</span>
              <span className="type-subhead ml-2 text-label-3">
                {p.phoneTypeLabel} · {p.sourceLabel}
              </span>
              <span className="type-subhead mt-0.5 block">
                <WhoAnswers line={p.line} why={p.lineWhy} />
              </span>
            </dd>
          </div>
        ) : null}
        {p.blocked ? (
          <p className="type-subhead text-label-2">
            <Status tone="bad">Do not contact{p.blockReason ? `: ${p.blockReason}` : ''}</Status>
          </p>
        ) : canEdit && (p.phone || p.email) ? (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <ContactButtons target={{ phone: p.phone, phoneType: p.phoneType, email: p.email, message }} onOpen={onOpen} />
            {p.phone ? (
              <button type="button" onClick={onWrong} className={plainClass('small')}>
                Wrong number
              </button>
            ) : null}
          </div>
        ) : null}
        {p.sourceUrl ? (
          <a href={p.sourceUrl} target="_blank" rel="noopener noreferrer" className="type-caption inline-flex items-center gap-1 text-label-3 hover:text-label-1">
            <ExternalLink aria-hidden className="size-3" />
            {p.sourceIsLinkedIn ? 'LinkedIn profile (message them there)' : 'Where we found it'}
          </a>
        ) : null}
      </dl>
    </li>
  )
}

/** The people at the company we can reach, the owner of the lead, and the company's own pages. */
export function People({
  view,
  canEdit,
  isAdmin,
  team,
  onOpen,
  onWrong,
}: {
  view: LeadView
  canEdit: boolean
  isAdmin: boolean
  team: { id: string; name: string }[]
  onOpen: (channel: Channel) => void
  onWrong: () => void
}) {
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="People" className={panel}>
        {view.people.length ? (
          <ul>
            {view.people.map((p) => (
              <Person key={p.id} p={p} message={view.message} canEdit={canEdit} onOpen={onOpen} onWrong={onWrong} />
            ))}
          </ul>
        ) : (
          <div className="px-5 py-8 lg:px-[26px]">
            <h3 className="type-headline text-label-1">No published contact yet</h3>
            <p className="type-body mt-1 text-label-3">We only use a number or email the company published itself. The engine checks again on its next run.</p>
          </div>
        )}
      </section>
      {view.website || view.mapsUrl || isAdmin ? (
        <section aria-label="Company" className={cx(panel, 'flex flex-col gap-4 px-5 py-5 lg:px-[26px]')}>
          {isAdmin ? <OwnerSelect leadId={view.id} ownerId={view.ownerId} team={team} /> : null}
          {view.website || view.mapsUrl ? (
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {view.website ? (
                <a href={view.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-label-1 hover:underline">
                  <Globe aria-hidden className="size-4 text-label-3" strokeWidth={1.75} />
                  {view.host || 'Website'}
                </a>
              ) : null}
              {view.mapsUrl ? (
                <a href={view.mapsUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-label-1 hover:underline">
                  <MapPin aria-hidden className="size-4 text-label-3" strokeWidth={1.75} />
                  Google listing
                </a>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}

function OwnerSelect({ leadId, ownerId, team }: { leadId: string; ownerId: string | null; team: { id: string; name: string }[] }) {
  const id = useId()
  const { pending, run } = useRun()
  const [value, setValue] = useState(ownerId ?? '')
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className={eyebrow}>
        Owner
      </label>
      <Select
        id={id}
        value={value}
        disabled={pending}
        className="max-w-xs"
        onChange={(e) => {
          const next = e.currentTarget.value
          const prev = value
          setValue(next)
          run(async () => {
            const r = await updateOwner({ leadId, ownerId: next || null })
            if (!r.ok) setValue(prev)
            return r
          })
        }}
      >
        <option value="">Nobody yet</option>
        {team.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </Select>
    </div>
  )
}
