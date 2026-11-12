'use client'

import { useRouter } from 'next/navigation'
import { useTransition } from 'react'
import { filtersToQuery, type LeadFilters } from '@/lib/leads-filters'

/** Navigates the Leads list to a new filter set. Any filter change goes back to page 1. */
export function useFilterNav(current: LeadFilters) {
  const router = useRouter()
  const [pending, startTransition] = useTransition()
  const go = (patch: Partial<LeadFilters>, opts: { keepPage?: boolean } = {}) => {
    const next = { ...current, ...patch, page: opts.keepPage ? (patch.page ?? current.page) : (patch.page ?? 1) }
    const qs = filtersToQuery(next)
    startTransition(() => router.push(qs ? `/leads?${qs}` : '/leads', { scroll: false }))
  }
  return { go, pending }
}
