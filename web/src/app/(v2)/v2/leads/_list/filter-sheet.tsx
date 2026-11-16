'use client'

import Link from 'next/link'
import { useState, useTransition } from 'react'
import { Trash2 } from 'lucide-react'
import { deleteView, saveView } from '@/app/(app)/leads/actions'
import { Button } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { Select } from '@/components/ui2/select'
import { SheetClose, SheetContent } from '@/components/ui2/sheet'
import { STAGE_V2 } from '@/components/ui2/stage-label'
import { toast } from '@/components/ui2/toast'
import { GRADES } from '@/lib/grades'
import { EMPTY_FILTERS, SORTS, filtersToQuery, type LeadFilters, type SortKey } from '@/lib/leads-filters'
import type { SavedView } from '@/lib/queries/page-data'
import { countryLabel, PITCH_MODES, SIGNAL_TYPES } from '@/lib/signals'
import { STAGE_VALUES } from '@/lib/stages'
import { eyebrow, outlineClass, plainClass } from '../_ui/marks'
import { fieldClass } from '../_ui/stage-move'

export type FilterOptions = {
  segments: { id: string; label: string }[]
  countries: string[]
  cities: string[]
  team: { id: string; name: string }[]
  showOwner: boolean
}

type ListKey = 'seg' | 'country' | 'city' | 'grade' | 'signal' | 'stage' | 'pitch'

const check = 'size-[18px] shrink-0 accent-[var(--ui-label-2)]'

function Choices({
  title,
  items,
  value,
  onChange,
  columns = 2,
}: {
  title: string
  items: { value: string; label: string }[]
  value: readonly string[]
  onChange: (next: string[]) => void
  columns?: 1 | 2
}) {
  if (!items.length) return null
  return (
    <fieldset className="flex flex-col gap-1 py-4 hairline-b">
      <legend className={cx(eyebrow, 'mb-2')}>{title}</legend>
      <div className={cx('grid gap-x-4', columns === 2 ? 'grid-cols-2' : 'grid-cols-1')}>
        {items.map((it) => (
          <label key={it.value} className="flex min-h-11 cursor-pointer items-center gap-3 text-label-1 lg:min-h-8">
            <input
              type="checkbox"
              className={check}
              checked={value.includes(it.value)}
              onChange={(e) => onChange(e.currentTarget.checked ? [...value, it.value] : value.filter((v) => v !== it.value))}
            />
            <span className="min-w-0 truncate">{it.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/** Every filter the list has, in a sheet: applied together, kept in the URL so a view is a link. */
export function FilterSheet({
  filters,
  options,
  views,
  onApply,
}: {
  filters: LeadFilters
  options: FilterOptions
  views: { mine: SavedView[]; shared: SavedView[] }
  onApply: (next: LeadFilters) => void
}) {
  const [f, setF] = useState<LeadFilters>(filters)
  const set = <K extends keyof LeadFilters>(k: K, v: LeadFilters[K]) => setF((cur) => ({ ...cur, [k]: v }))
  const list = (k: ListKey) => (next: string[]) => setF((cur) => ({ ...cur, [k]: next }) as LeadFilters)
  return (
    <SheetContent title="Filter leads" description="Search, scope and these filters all apply together.">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          onApply({ ...f, page: 1 })
        }}
        className="flex flex-col"
      >
        <Choices title="Grade" items={GRADES.map((g) => ({ value: g, label: `Grade ${g}` }))} value={f.grade} onChange={list('grade')} />
        <Choices title="Stage" items={STAGE_VALUES.map((s) => ({ value: s, label: STAGE_V2[s].label }))} value={f.stage} onChange={list('stage')} />
        <Choices title="Segment" items={options.segments.map((s) => ({ value: s.id, label: s.label }))} value={f.seg} onChange={list('seg')} columns={1} />
        <Choices title="Country" items={options.countries.map((c) => ({ value: c, label: countryLabel(c) }))} value={f.country} onChange={list('country')} />
        <Choices title="City" items={options.cities.slice(0, 60).map((c) => ({ value: c, label: c }))} value={f.city} onChange={list('city')} />
        <Choices title="Signal" items={SIGNAL_TYPES.map((s) => ({ value: s.value, label: s.label }))} value={f.signal} onChange={list('signal')} columns={1} />
        <Choices title="Pitch" items={PITCH_MODES.map((p) => ({ value: p.value, label: p.label }))} value={f.pitch} onChange={list('pitch')} />

        <fieldset className="flex flex-col gap-1 py-4 hairline-b">
          <legend className={cx(eyebrow, 'mb-2')}>More</legend>
          <label className="flex min-h-11 items-center gap-3 lg:min-h-8">
            <input type="checkbox" className={check} checked={f.mobile} onChange={(e) => set('mobile', e.currentTarget.checked)} />
            Has a mobile number
          </label>
          <label className="flex min-h-11 items-center gap-3 lg:min-h-8">
            <input type="checkbox" className={check} checked={f.overdue} onChange={(e) => set('overdue', e.currentTarget.checked)} />
            Next step overdue
          </label>
          {options.showOwner ? (
            <label className="mt-2 flex flex-col gap-1.5">
              <span className="type-subhead text-label-3">Owner</span>
              <Select value={f.owner} onChange={(e) => set('owner', e.currentTarget.value)}>
                <option value="">Anyone</option>
                <option value="me">Me</option>
                <option value="none">Nobody yet</option>
                {options.team.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </label>
          ) : null}
          <div className="mt-2 grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="type-subhead text-label-3">Found from</span>
              <input type="date" value={f.from} onChange={(e) => set('from', e.currentTarget.value)} className={fieldClass} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="type-subhead text-label-3">to</span>
              <input type="date" value={f.to} onChange={(e) => set('to', e.currentTarget.value)} className={fieldClass} />
            </label>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="type-subhead text-label-3">Sort by</span>
              <Select value={f.sort} onChange={(e) => set('sort', e.currentTarget.value as SortKey)}>
                {Object.entries(SORTS).map(([k, s]) => (
                  <option key={k} value={k}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="type-subhead text-label-3">Order</span>
              <Select value={f.dir} onChange={(e) => set('dir', e.currentTarget.value as 'asc' | 'desc')}>
                <option value="desc">Newest or highest first</option>
                <option value="asc">Oldest or lowest first</option>
              </Select>
            </label>
          </div>
        </fieldset>

        <div className="sticky bottom-0 -mx-4 mt-2 flex items-center gap-2 bg-overlay px-4 py-3 lg:-mx-5 lg:px-5">
          <button type="button" className={plainClass()} onClick={() => setF({ ...EMPTY_FILTERS, q: f.q })}>
            Clear all
          </button>
          <Button type="submit" variant="primary" className="ml-auto">
            Show leads
          </Button>
        </div>
      </form>
      <Views views={views} current={filters} />
    </SheetContent>
  )
}

function Views({ views, current }: { views: { mine: SavedView[]; shared: SavedView[] }; current: LeadFilters }) {
  const [pending, start] = useTransition()
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  const qs = filtersToQuery(current, { page: 1 })
  const row = (v: SavedView, mine: boolean) => (
    <li key={v.id} className="flex items-center gap-1">
      <SheetClose asChild>
        <Link href={v.qs ? `/leads?${v.qs}` : '/leads'} className="flex min-h-11 min-w-0 flex-1 items-center truncate rounded-control px-2 text-label-1 hover:bg-fill-3 lg:min-h-9">
          {v.name}
        </Link>
      </SheetClose>
      {mine ? (
        <button
          type="button"
          disabled={pending}
          aria-label={`Delete view ${v.name}`}
          className={plainClass('small', 'w-9 px-0')}
          onClick={() =>
            start(async () => {
              const r = await deleteView(v.id)
              if (r.ok) toast(r.message ?? 'Deleted')
              else toast.error(r.message)
            })
          }
        >
          <Trash2 aria-hidden />
        </button>
      ) : null}
    </li>
  )
  return (
    <section aria-labelledby="views-h" className="mt-6 flex flex-col gap-2">
      <h3 id="views-h" className={eyebrow}>
        Saved views
      </h3>
      {views.mine.length || views.shared.length ? (
        <ul>
          {views.mine.map((v) => row(v, true))}
          {views.shared.map((v) => row(v, false))}
        </ul>
      ) : (
        <p className="type-subhead text-label-3">None yet. Save the current search and filters to open them in one tap.</p>
      )}
      <form
        className="mt-1 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          start(async () => {
            const r = await saveView({ name, query: qs, shared })
            if (r.ok) {
              toast(r.message ?? 'Saved')
              setName('')
            } else toast.error(r.message)
          })
        }}
      >
        <input value={name} onChange={(e) => setName(e.currentTarget.value)} maxLength={60} placeholder="Name this view" aria-label="View name" className={cx(fieldClass, 'min-w-0 flex-1')} />
        <label className="flex min-h-11 items-center gap-2 text-label-2 lg:min-h-9">
          <input type="checkbox" className={check} checked={shared} onChange={(e) => setShared(e.currentTarget.checked)} />
          Share
        </label>
        <button type="submit" disabled={!name.trim() || pending} className={outlineClass('small')}>
          Save view
        </button>
      </form>
    </section>
  )
}
