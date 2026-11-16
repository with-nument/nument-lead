'use client'

import { usePathname } from 'next/navigation'
import type { Role } from '@/lib/roles'
import type { NavCounts } from '@/lib/queries/page-data'
import { cx } from '@/components/ui2/cx'
import { IntentLink } from './intent-link'
import { isCurrent, navCount, PRIMARY_NAV, secondaryFor, type NavItem } from './nav-items'

function SidebarLink({ item, current, count, secondary }: { item: NavItem; current: boolean; count?: number | null; secondary?: boolean }) {
  const Icon = item.icon
  return (
    <li>
      <IntentLink
        href={item.href}
        aria-current={current ? 'page' : undefined}
        className={cx(
          'flex items-center gap-3 rounded-control px-3 transition-colors duration-[var(--ui-dur-1)]',
          secondary ? 'h-9 text-[14px]' : 'h-10 text-[15px]',
          current
            ? 'bg-panel font-[550] text-label-1 shadow-[var(--ui-shadow-panel)]'
            : cx('hover:bg-fill-3 hover:text-label-1', secondary ? 'text-label-3' : 'text-label-2'),
        )}
      >
        <Icon className={cx('shrink-0', secondary ? 'size-4' : 'size-[18px]')} />
        <span className="flex-1">{item.label}</span>
        {count ? (
          <span className={cx('text-[13px] tabular-nums', current ? 'font-[550] text-label-1' : 'text-label-3')}>
            {count}
            <span className="sr-only"> waiting</span>
          </span>
        ) : null}
      </IntentLink>
    </li>
  )
}

/** The sidebar's two groups, the second at the foot. `role` is null until the session streams in (admin-only items wait). */
export function SidebarLinks({ role, counts }: { role: Role | null; counts?: NavCounts | null }) {
  return <SidebarLinksView path={usePathname()} role={role} counts={counts} />
}

/** The links for a given path. With `path` null nothing is marked current (the static fallback, see TabBarView). */
export function SidebarLinksView({ path, role, counts }: { path: string | null; role: Role | null; counts?: NavCounts | null }) {
  const here = (href: string) => path !== null && isCurrent(path, href)
  return (
    <>
      <ul role="list" className="flex flex-col gap-0.5">
        {PRIMARY_NAV.map((item) => (
          <SidebarLink key={item.href} item={item} current={here(item.href)} count={navCount(item.href, counts)} />
        ))}
      </ul>
      <ul role="list" className="mt-auto flex flex-col gap-0.5 pt-4">
        {secondaryFor(role).map((item) => (
          <SidebarLink key={item.href} item={item} current={here(item.href)} secondary />
        ))}
      </ul>
    </>
  )
}
