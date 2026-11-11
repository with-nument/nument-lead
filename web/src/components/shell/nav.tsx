'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CalendarCheck, ChartColumn, Cpu, Inbox, List, Settings, SquareKanban } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { Role } from '@/lib/roles'

const ITEMS = [
  { href: '/', label: 'Today', icon: CalendarCheck, roles: ['admin', 'caller', 'viewer'] },
  { href: '/leads', label: 'Leads', icon: List, roles: ['admin', 'caller', 'viewer'] },
  { href: '/pipeline', label: 'Pipeline', icon: SquareKanban, roles: ['admin', 'caller', 'viewer'] },
  { href: '/insights', label: 'Insights', icon: ChartColumn, roles: ['admin', 'caller', 'viewer'] },
  { href: '/engine', label: 'Engine', icon: Cpu, roles: ['admin'] },
  { href: '/inbox', label: 'Inbox', icon: Inbox, roles: ['admin'] },
  { href: '/settings', label: 'Settings', icon: Settings, roles: ['admin', 'caller', 'viewer'] },
] as const

const isActive = (path: string, href: string) => (href === '/' ? path === '/' : path === href || path.startsWith(`${href}/`))

/** Sidebar links for the signed-in role. Pages a role cannot open are not shown at all. */
export function NavLinks({ role, onNavigate }: { role: Role | null; onNavigate?: () => void }) {
  const path = usePathname()
  const items = ITEMS.filter((i) => (role ? (i.roles as readonly string[]).includes(role) : i.roles.length === 3))
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map(({ href, label, icon: Icon }) => {
        const active = isActive(path, href)
        return (
          <li key={href}>
            <Link
              href={href}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'relative flex h-9 items-center gap-2.5 rounded-lg px-3 text-base transition-colors duration-150',
                active ? 'bg-surface-2 text-tx-1' : 'text-tx-3 hover:bg-surface-2/70 hover:text-tx-1',
              )}
            >
              {active ? <span aria-hidden className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-indigo-600" /> : null}
              <Icon aria-hidden className={cn('size-4', active ? 'text-indigo-800' : 'text-tx-4')} strokeWidth={1.75} />
              {label}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

/** Same list without the current-page state, for the prerendered shell. */
export function NavLinksStatic() {
  return (
    <ul className="flex flex-col gap-0.5">
      {ITEMS.filter((i) => i.roles.length === 3).map(({ href, label, icon: Icon }) => (
        <li key={href}>
          <Link href={href} className="flex h-9 items-center gap-2.5 rounded-lg px-3 text-base text-tx-3 hover:bg-surface-2/70 hover:text-tx-1">
            <Icon aria-hidden className="size-4 text-tx-4" strokeWidth={1.75} />
            {label}
          </Link>
        </li>
      ))}
    </ul>
  )
}
