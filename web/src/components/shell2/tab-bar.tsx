'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cx } from '@/components/ui2/cx'
import { isCurrent, PRIMARY_NAV } from './nav-items'

/** iPhone-style tab bar below 1024 px: the five primary places, always one tap away. */
export function TabBar() {
  const path = usePathname()
  return (
    <nav aria-label="Main" className="material-bar hairline-t fixed inset-x-0 bottom-0 z-30 pb-[env(safe-area-inset-bottom)] lg:hidden">
      <ul role="list" className="mx-auto grid h-[var(--ui-tabbar-h)] max-w-[640px] grid-cols-5 px-[max(8px,env(safe-area-inset-left))]">
        {PRIMARY_NAV.map((item) => {
          const current = isCurrent(path, item.href)
          const Icon = item.icon
          return (
            <li key={item.href} className="flex">
              <Link
                href={item.href}
                aria-current={current ? 'page' : undefined}
                className={cx(
                  'flex flex-1 flex-col items-center justify-center gap-[3px] pt-1 transition-colors duration-[var(--ui-dur-1)] focus-visible:-outline-offset-4',
                  current ? 'text-accent' : 'text-label-3',
                )}
              >
                <Icon aria-hidden className="size-6" strokeWidth={current ? 2.2 : 1.8} />
                <span className="type-tab">{item.label}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
