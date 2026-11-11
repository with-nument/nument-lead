'use client'

import { useRouter } from 'next/navigation'
import { useTransition } from 'react'
import { Checkbox, Select } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { countryLabel } from '@/lib/signals'

export type BoardFilterState = { seg: string; country: string; owner: string; overdue: boolean }

export function BoardFilters({
  value,
  segments,
  countries,
  team,
  showOwner,
}: {
  value: BoardFilterState
  segments: { id: string; label: string }[]
  countries: string[]
  team: { id: string; name: string }[]
  showOwner: boolean
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const go = (patch: Partial<BoardFilterState>) => {
    const next = { ...value, ...patch }
    const p = new URLSearchParams()
    if (next.seg) p.set('seg', next.seg)
    if (next.country) p.set('country', next.country)
    if (next.owner) p.set('owner', next.owner)
    if (next.overdue) p.set('overdue', '1')
    start(() => router.push(p.size ? `/pipeline?${p}` : '/pipeline', { scroll: false }))
  }
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <div className="w-48">
        <label htmlFor="pf-seg" className="sr-only">
          Segment
        </label>
        <Select id="pf-seg" value={value.seg} onChange={(e) => go({ seg: e.currentTarget.value })}>
          <option value="">All segments</option>
          {segments.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </Select>
      </div>
      {countries.length > 1 ? (
        <div className="w-36">
          <label htmlFor="pf-country" className="sr-only">
            Country
          </label>
          <Select id="pf-country" value={value.country} onChange={(e) => go({ country: e.currentTarget.value })}>
            <option value="">All countries</option>
            {countries.map((c) => (
              <option key={c} value={c}>
                {countryLabel(c)}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      {showOwner ? (
        <div className="w-44">
          <label htmlFor="pf-owner" className="sr-only">
            Owner
          </label>
          <Select id="pf-owner" value={value.owner} onChange={(e) => go({ owner: e.currentTarget.value })}>
            <option value="">Any owner</option>
            <option value="me">Mine</option>
            <option value="none">No owner</option>
            {team.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      <label className="flex h-10 cursor-pointer items-center gap-2 rounded-full px-3 text-base text-tx-2 hover:bg-surface-2">
        <Checkbox checked={value.overdue} onChange={(e) => go({ overdue: e.currentTarget.checked })} />
        Only overdue
      </label>
      {pending ? <Spinner className="text-tx-3" /> : null}
    </div>
  )
}
