'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { Role } from '@/lib/roles'
import { cx } from '@/components/ui2/cx'
import { isCurrent, PRIMARY_NAV, secondaryFor, type NavItem } from './nav-items'

function SidebarLink({ item, current }: { item: NavItem; current: boolean }) {
  const Icon = item.icon
  return (
    <li>
      <Link
        href={item.href}
        aria-current={current ? 'page' : undefined}
        className={cx(
          'flex h-9 items-center gap-3 rounded-[9px] px-2.5 text-[15px] transition-colors duration-[var(--ui-dur-1)]',
          current ? 'bg-fill-1 text-label-1' : 'text-label-1 hover:bg-fill-3',
        )}
      >
        <Icon aria-hidden className={cx('size-[18px] shrink-0', current ? 'text-accent' : 'text-label-2')} strokeWidth={current ? 2.25 : 1.9} />
        {item.label}
      </Link>
    </li>
  )
}

/** The sidebar's two groups. `role` is null until the session streams in (admin-only items wait). */
export function SidebarLinks({ role }: { role: Role | null }) {
  const path = usePathname()
  return (
    <>
      <ul role="list" className="flex flex-col gap-0.5">
        {PRIMARY_NAV.map((item) => (
          <SidebarLink key={item.href} item={item} current={isCurrent(path, item.href)} />
        ))}
      </ul>
      <ul role="list" className="mt-6 flex flex-col gap-0.5">
        {secondaryFor(role).map((item) => (
          <SidebarLink key={item.href} item={item} current={isCurrent(path, item.href)} />
        ))}
      </ul>
    </>
  )
}
