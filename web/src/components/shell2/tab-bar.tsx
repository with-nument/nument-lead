'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { NavCounts } from '@/lib/queries/page-data'
import { cx } from '@/components/ui2/cx'
import { isCurrent, PRIMARY_NAV } from './nav-items'

/** The phone tab bar below 1024 px (mockups): the five places, one tap away, with the Inbox count as a badge. */
export function TabBar({ counts }: { counts?: NavCounts | null }) {
  const path = usePathname()
  const inbox = counts?.inboxNew ?? 0
  return (
    <nav aria-label="Main" className="hairline-t fixed inset-x-0 bottom-0 z-30 bg-tabbar pb-[env(safe-area-inset-bottom)] lg:hidden">
      <ul role="list" className="mx-auto grid h-[var(--ui-tabbar-h)] max-w-[640px] grid-cols-5 px-[max(6px,env(safe-area-inset-left))]">
        {PRIMARY_NAV.map((item) => {
          const current = isCurrent(path, item.href)
          const Icon = item.icon
          const badge = item.href === '/inbox' && inbox > 0 ? inbox : null
          return (
            <li key={item.href} className="flex">
              <Link
                href={item.href}
                aria-current={current ? 'page' : undefined}
                className={cx(
                  'relative flex flex-1 flex-col items-center justify-center gap-1 transition-colors duration-[var(--ui-dur-1)] focus-visible:-outline-offset-4',
                  current ? 'text-label-1' : 'text-label-3',
                )}
              >
                <span className="relative">
                  <Icon className="size-[22px]" strokeWidth={current ? 1.9 : 1.6} />
                  {badge ? (
                    <span className="absolute -top-1.5 left-[calc(100%-6px)] grid h-4 min-w-4 place-items-center rounded-full bg-accent-fill px-1 text-[10px] font-semibold text-on-accent tabular-nums">
                      {badge > 99 ? '99+' : badge}
                      <span className="sr-only"> new</span>
                    </span>
                  ) : null}
                </span>
                <span className={cx('type-tab', current && 'font-semibold')}>{item.label}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
