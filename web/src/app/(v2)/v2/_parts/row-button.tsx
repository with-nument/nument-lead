'use client'

import { ChevronRight } from 'lucide-react'
import { cx } from '@/components/ui2/cx'

/** A panel row that opens something (a sheet): label, value and a chevron, the whole row clickable. */
export function RowButton({ label, children, onClick, className }: { label: string; children: React.ReactNode; onClick: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'flex min-h-14 w-full items-center gap-3.5 px-4 py-3 text-left text-[15px] transition-colors duration-[var(--ui-dur-1)] hover:bg-fill-3 active:bg-fill-2 focus-visible:-outline-offset-2 lg:px-5 lg:text-[14.5px]',
        className,
      )}
    >
      <span className="w-[112px] shrink-0 text-label-3 sm:w-[130px]">{label}</span>
      <span className="min-w-0 flex-1 truncate text-label-1">{children}</span>
      <ChevronRight aria-hidden className="size-4 shrink-0 text-label-3" />
    </button>
  )
}
