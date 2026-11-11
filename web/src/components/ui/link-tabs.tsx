'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/cn'

/** Page-level tabs as links: inactive grey text, active ink text with a 2px indigo underline. */
export function LinkTabs({ tabs, className }: { tabs: { href: string; label: string }[]; className?: string }) {
  const path = usePathname()
  return (
    <nav aria-label="Sections" className={cn('mb-6 flex gap-5 overflow-x-auto border-b border-line-2', className)}>
      {tabs.map((t) => {
        const active = path === t.href
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              '-mb-px flex h-10 shrink-0 items-center border-b-2 text-base transition-colors',
              active ? 'border-indigo-600 text-tx-1' : 'border-transparent text-tx-3 hover:text-tx-1',
            )}
          >
            {t.label}
          </Link>
        )
      })}
    </nav>
  )
}
