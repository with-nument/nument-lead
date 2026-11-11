import Link from 'next/link'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { buttonClasses } from '@/components/ui/button'
import { formatNumber } from '@/lib/format'
import { filtersToQuery, type LeadFilters } from '@/lib/leads-filters'

export function Pagination({ filters, total, pageSize }: { filters: LeadFilters; total: number; pageSize: number }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const page = Math.min(filters.page, pages)
  const from = total ? (page - 1) * pageSize + 1 : 0
  const to = Math.min(total, page * pageSize)
  const href = (p: number) => {
    const qs = filtersToQuery(filters, { page: p })
    return qs ? `/leads?${qs}` : '/leads'
  }
  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-3 border-t border-line-2 px-4 py-3 sm:px-5">
      <span className="text-sm text-tx-3">
        {formatNumber(from)} to {formatNumber(to)} of {formatNumber(total)}
      </span>
      <div className="flex items-center gap-1">
        {page > 1 ? (
          <Link href={href(page - 1)} scroll={false} className={buttonClasses('ghost', 'sm')} aria-label="Previous page">
            <ChevronLeft aria-hidden />
            Previous
          </Link>
        ) : (
          <span className={buttonClasses('ghost', 'sm', 'pointer-events-none opacity-40')} aria-disabled>
            <ChevronLeft aria-hidden />
            Previous
          </span>
        )}
        {page < pages ? (
          <Link href={href(page + 1)} scroll={false} className={buttonClasses('ghost', 'sm')} aria-label="Next page">
            Next
            <ChevronRight aria-hidden />
          </Link>
        ) : (
          <span className={buttonClasses('ghost', 'sm', 'pointer-events-none opacity-40')} aria-disabled>
            Next
            <ChevronRight aria-hidden />
          </span>
        )}
      </div>
    </nav>
  )
}
