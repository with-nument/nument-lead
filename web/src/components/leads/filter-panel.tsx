'use client'

import { useId } from 'react'
import { Checkbox } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/cn'
import { GRADES } from '@/lib/grades'
import { EMPTY_FILTERS, activeFilterCount, type LeadFilters } from '@/lib/leads-filters'
import { PITCH_MODES, SIGNAL_TYPES, countryLabel } from '@/lib/signals'
import { STAGES } from '@/lib/stages'
import { useFilterNav } from './use-filter-nav'

export type FilterOptions = {
  segments: { id: string; label: string }[]
  countries: string[]
  cities: string[]
  team: { id: string; name: string }[]
}

type ListKey = 'seg' | 'country' | 'city' | 'grade' | 'signal' | 'stage' | 'pitch'

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="border-b border-line-2 py-4 first:pt-0 last:border-b-0">
      <legend className="label-mono mb-2">{title}</legend>
      {children}
    </fieldset>
  )
}

function CheckList({
  name,
  options,
  selected,
  onToggle,
  max = 8,
}: {
  name: string
  options: { value: string; label: string }[]
  selected: string[]
  onToggle: (value: string, on: boolean) => void
  max?: number
}) {
  const id = useId()
  const shown = options.length > max ? [...options.filter((o) => selected.includes(o.value)), ...options.filter((o) => !selected.includes(o.value))].slice(0, max) : options
  return (
    <ul className="flex flex-col gap-0.5">
      {shown.map((o) => {
        const checkboxId = `${id}-${o.value}`
        return (
          <li key={o.value}>
            <label htmlFor={checkboxId} className="flex min-h-8 cursor-pointer items-center gap-2.5 rounded-lg px-1.5 text-base text-tx-2 hover:bg-surface-2">
              <Checkbox id={checkboxId} name={name} value={o.value} checked={selected.includes(o.value)} onChange={(e) => onToggle(o.value, e.currentTarget.checked)} />
              <span className="truncate">{o.label}</span>
            </label>
          </li>
        )
      })}
      {options.length > max ? <li className="px-1.5 pt-1 text-xs text-tx-3">{options.length - max} more, use search to narrow down</li> : null}
    </ul>
  )
}

/** The filter panel. Every change updates the URL, so the view can be shared or saved. */
export function FilterPanel({ filters, options, showOwner }: { filters: LeadFilters; options: FilterOptions; showOwner: boolean }) {
  const { go, pending } = useFilterNav(filters)
  const toggle = (key: ListKey) => (value: string, on: boolean) => {
    const list = filters[key] as string[]
    go({ [key]: on ? [...list, value] : list.filter((v) => v !== value) } as Partial<LeadFilters>)
  }
  const count = activeFilterCount(filters)
  const fromId = useId()
  const toId = useId()
  const ownerId = useId()

  return (
    <div className={cn('transition-opacity', pending && 'opacity-70')}>
      <div className="mb-3 flex h-6 items-center justify-between">
        <span className="text-sm font-medium text-tx-2">
          Filters{count ? ` · ${count}` : ''} {pending ? <Spinner className="ml-1 size-3 align-[-1px] text-tx-3" /> : null}
        </span>
        {count ? (
          <button type="button" className="text-sm text-tx-3 hover:text-indigo-800" onClick={() => go({ ...EMPTY_FILTERS, sort: filters.sort, dir: filters.dir })}>
            Clear all
          </button>
        ) : null}
      </div>

      <Group title="Stage">
        <CheckList name="stage" options={STAGES.map((s) => ({ value: s.value, label: s.label }))} selected={filters.stage} onToggle={toggle('stage')} max={12} />
      </Group>
      <Group title="Grade">
        <div className="flex gap-1.5" role="group" aria-label="Grade">
          {GRADES.map((g) => {
            const on = filters.grade.includes(g)
            return (
              <button
                key={g}
                type="button"
                aria-pressed={on}
                onClick={() => toggle('grade')(g, !on)}
                className={cn(
                  'grid size-9 place-items-center rounded-lg border text-sm font-semibold transition-colors',
                  on ? 'border-slate bg-slate text-white' : 'border-line bg-surface text-tx-2 hover:bg-surface-2',
                )}
              >
                {g}
              </button>
            )
          })}
        </div>
      </Group>
      <Group title="Segment">
        <CheckList name="seg" options={options.segments.map((s) => ({ value: s.id, label: s.label }))} selected={filters.seg} onToggle={toggle('seg')} />
      </Group>
      {options.countries.length > 1 ? (
        <Group title="Country">
          <CheckList name="country" options={options.countries.map((c) => ({ value: c, label: countryLabel(c) }))} selected={filters.country} onToggle={toggle('country')} />
        </Group>
      ) : null}
      {options.cities.length ? (
        <Group title="City">
          <CheckList name="city" options={options.cities.map((c) => ({ value: c, label: c }))} selected={filters.city} onToggle={toggle('city')} max={10} />
        </Group>
      ) : null}
      <Group title="Signal">
        <CheckList name="signal" options={SIGNAL_TYPES.map((s) => ({ value: s.value, label: s.label }))} selected={filters.signal} onToggle={toggle('signal')} max={12} />
      </Group>
      <Group title="Pitch mode">
        <CheckList name="pitch" options={PITCH_MODES.map((p) => ({ value: p.value, label: p.label }))} selected={filters.pitch} onToggle={toggle('pitch')} />
      </Group>
      <Group title="More">
        <div className="flex flex-col gap-0.5">
          <label className="flex min-h-8 cursor-pointer items-center gap-2.5 rounded-lg px-1.5 text-base text-tx-2 hover:bg-surface-2">
            <Checkbox checked={filters.mobile} onChange={(e) => go({ mobile: e.currentTarget.checked })} />
            Has a mobile number
          </label>
          <label className="flex min-h-8 cursor-pointer items-center gap-2.5 rounded-lg px-1.5 text-base text-tx-2 hover:bg-surface-2">
            <Checkbox checked={filters.overdue} onChange={(e) => go({ overdue: e.currentTarget.checked })} />
            Overdue next step
          </label>
        </div>
        {showOwner ? (
          <div className="mt-3 flex flex-col gap-1.5">
            <label htmlFor={ownerId} className="text-sm text-tx-3">
              Owner
            </label>
            <select
              id={ownerId}
              value={filters.owner}
              onChange={(e) => go({ owner: e.currentTarget.value })}
              className="h-9 rounded-xl border border-line bg-surface px-3 text-base focus-visible:outline-none focus-visible:focus-ring"
            >
              <option value="">Anyone</option>
              <option value="me">Me</option>
              <option value="none">Nobody yet</option>
              {options.team.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={fromId} className="text-sm text-tx-3">
              Added from
            </label>
            <input
              id={fromId}
              type="date"
              value={filters.from}
              max={filters.to || undefined}
              onChange={(e) => go({ from: e.currentTarget.value })}
              className="h-9 min-w-0 rounded-xl border border-line bg-surface px-2 text-sm focus-visible:outline-none focus-visible:focus-ring"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={toId} className="text-sm text-tx-3">
              to
            </label>
            <input
              id={toId}
              type="date"
              value={filters.to}
              min={filters.from || undefined}
              onChange={(e) => go({ to: e.currentTarget.value })}
              className="h-9 min-w-0 rounded-xl border border-line bg-surface px-2 text-sm focus-visible:outline-none focus-visible:focus-ring"
            />
          </div>
        </div>
      </Group>
    </div>
  )
}
