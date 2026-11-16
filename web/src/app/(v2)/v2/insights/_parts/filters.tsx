'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Choice } from '@/app/(v2)/v2/_parts/choice'
import { Select } from '@/components/ui2/select'
import { insightsHref, PERIODS, type InsightsQuery, type Period } from '../filters'

const PERIOD_LABEL: Record<Period, string> = { '7': '7 days', '30': '30 days', '90': '90 days' }

/** The period, segment and country above everything they scope. */
export function InsightsFilters({ value, segments, countries }: { value: InsightsQuery; segments: { id: string; label: string }[]; countries: { id: string; label: string }[] }) {
  const router = useRouter()
  const [pending, start] = useTransition()
  const go = (patch: Partial<InsightsQuery>) => start(() => router.push(insightsHref({ ...value, ...patch }), { scroll: false }))
  return (
    <div aria-busy={pending || undefined} className="mb-7 flex flex-wrap items-center gap-2 transition-opacity aria-busy:opacity-60">
      <Choice
        items={PERIODS.map((p) => ({ value: p, label: PERIOD_LABEL[p] }))}
        value={value.period}
        onValueChange={(period) => go({ period })}
        label="Period"
        className="w-full sm:w-[300px]"
      />
      <Select aria-label="Segment" value={value.seg} onChange={(e) => go({ seg: e.currentTarget.value })} className="min-w-0 flex-1 sm:w-48 sm:flex-none">
        <option value="">All segments</option>
        {segments.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label}
          </option>
        ))}
      </Select>
      <Select aria-label="Country" value={value.country} onChange={(e) => go({ country: e.currentTarget.value })} className="min-w-0 flex-1 sm:w-40 sm:flex-none">
        <option value="">All countries</option>
        {countries.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
          </option>
        ))}
      </Select>
    </div>
  )
}

/** "Group by" for the What works list. */
export function GroupSelect({ value, groups }: { value: InsightsQuery; groups: { value: string; label: string }[] }) {
  const router = useRouter()
  const [, start] = useTransition()
  return (
    <Select
      aria-label="Group by"
      value={value.group}
      onChange={(e) => start(() => router.push(insightsHref({ ...value, group: e.currentTarget.value as InsightsQuery['group'] }), { scroll: false }))}
      className="w-40"
    >
      {groups.map((g) => (
        <option key={g.value} value={g.value}>
          By {g.label.toLowerCase()}
        </option>
      ))}
    </Select>
  )
}
