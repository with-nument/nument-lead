'use client'

import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { LeadFilters } from '@/lib/leads-filters'
import { useFilterNav } from './use-filter-nav'

/** Company name, phone digits or website. Updates the URL 350 ms after typing stops. */
export function SearchBox({ filters, className }: { filters: LeadFilters; className?: string }) {
  const { go, pending } = useFilterNav(filters)
  const [value, setValue] = useState(filters.q)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const schedule = (q: string) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => go({ q: q.trim() }), 350)
  }

  return (
    <div className={cn('relative', className)}>
      <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-tx-3" />
      <input
        type="search"
        value={value}
        onChange={(e) => {
          setValue(e.currentTarget.value)
          schedule(e.currentTarget.value)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            window.clearTimeout(timer.current)
            go({ q: value.trim() })
          }
        }}
        placeholder="Search company, phone or website"
        aria-label="Search leads"
        aria-busy={pending || undefined}
        className="h-10 w-full rounded-full border border-line bg-surface pr-9 pl-10 text-base placeholder:text-tx-4 focus-visible:outline-none focus-visible:focus-ring [&::-webkit-search-cancel-button]:hidden"
      />
      {value ? (
        <button
          type="button"
          aria-label="Clear search"
          onClick={() => {
            setValue('')
            window.clearTimeout(timer.current)
            go({ q: '' })
          }}
          className="absolute top-1/2 right-2 grid size-7 -translate-y-1/2 place-items-center rounded-full text-tx-3 hover:bg-surface-2"
        >
          <X className="size-3.5" />
        </button>
      ) : null}
    </div>
  )
}
