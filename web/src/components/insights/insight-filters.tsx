'use client'

import { useRouter } from 'next/navigation'
import { useTransition } from 'react'
import { Select } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/cn'
import { countryLabel } from '@/lib/signals'

export type InsightFilterValue = { from: string; to: string; seg: string; country: string; group: string; preset: string }

const PRESETS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]

/** One row of filters above everything they scope (date range first). */
export function InsightFilters({
  value,
  segments,
  countries,
  groups,
}: {
  value: InsightFilterValue
  segments: { id: string; label: string }[]
  countries: string[]
  groups: { value: string; label: string }[]
}) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const go = (patch: Partial<InsightFilterValue>) => {
    const next = { ...value, ...patch }
    const p = new URLSearchParams()
    if (next.preset && next.preset !== 'custom') p.set('days', next.preset)
    else {
      if (next.from) p.set('from', next.from)
      if (next.to) p.set('to', next.to)
    }
    if (next.seg) p.set('seg', next.seg)
    if (next.country) p.set('country', next.country)
    if (next.group && next.group !== 'segment') p.set('group', next.group)
    start(() => router.push(`/insights?${p}`, { scroll: false }))
  }
  const field = 'h-10 rounded-xl border border-line bg-surface px-3 text-base focus-visible:outline-none focus-visible:focus-ring'
  return (
    <div className={cn('mb-6 flex flex-wrap items-center gap-2', pending && 'opacity-70')}>
      <div className="flex rounded-full border border-line bg-surface p-0.5" role="group" aria-label="Date range">
        {PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            aria-pressed={value.preset === p.value}
            onClick={() => go({ preset: p.value })}
            className={cn('h-9 rounded-full px-3.5 text-sm transition-colors', value.preset === p.value ? 'bg-surface-2 text-tx-1 shadow-[var(--shadow-tab-active)]' : 'text-tx-3 hover:text-tx-1')}
          >
            {p.label}
          </button>
        ))}
      </div>
      <label className="sr-only" htmlFor="if-from">
        From
      </label>
      <input id="if-from" type="date" className={field} value={value.from} max={value.to} onChange={(e) => go({ preset: 'custom', from: e.currentTarget.value })} />
      <span className="text-sm text-tx-3">to</span>
      <label className="sr-only" htmlFor="if-to">
        To
      </label>
      <input id="if-to" type="date" className={field} value={value.to} min={value.from} onChange={(e) => go({ preset: 'custom', to: e.currentTarget.value })} />
      <div className="w-44">
        <label className="sr-only" htmlFor="if-seg">
          Segment
        </label>
        <Select id="if-seg" value={value.seg} onChange={(e) => go({ seg: e.currentTarget.value })}>
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
          <label className="sr-only" htmlFor="if-country">
            Country
          </label>
          <Select id="if-country" value={value.country} onChange={(e) => go({ country: e.currentTarget.value })}>
            <option value="">All countries</option>
            {countries.map((c) => (
              <option key={c} value={c}>
                {countryLabel(c)}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      <div className="w-44">
        <label className="sr-only" htmlFor="if-group">
          Compare by
        </label>
        <Select id="if-group" value={value.group} onChange={(e) => go({ group: e.currentTarget.value })}>
          {groups.map((g) => (
            <option key={g.value} value={g.value}>
              Compare by {g.label.toLowerCase()}
            </option>
          ))}
        </Select>
      </div>
      {pending ? <Spinner className="text-tx-3" /> : null}
    </div>
  )
}
