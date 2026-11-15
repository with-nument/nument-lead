import { ChartColumn, Cpu, Handshake, Inbox, Phone, Settings, Sun, UsersRound, type LucideIcon } from 'lucide-react'
import type { Role } from '@/lib/roles'
import { canonicalPath } from '@/lib/ui-flag'

export type NavItem = { href: string; label: string; icon: LucideIcon; adminOnly?: boolean }

/** The five places people work in: the sidebar on laptops, the tab bar on phones. */
export const PRIMARY_NAV: readonly NavItem[] = [
  { href: '/', label: 'Today', icon: Sun },
  { href: '/inbox', label: 'Inbox', icon: Inbox },
  { href: '/calls', label: 'Calls', icon: Phone },
  { href: '/deals', label: 'Deals', icon: Handshake },
  { href: '/leads', label: 'Leads', icon: UsersRound },
]

/** Everything else: lower in the sidebar, in the account sheet on phones. */
export const SECONDARY_NAV: readonly NavItem[] = [
  { href: '/insights', label: 'Insights', icon: ChartColumn },
  { href: '/engine', label: 'Engine', icon: Cpu, adminOnly: true },
  { href: '/settings', label: 'Settings', icon: Settings },
]

/** Secondary items this role may open. Before the role is known, only the ones everyone has. */
export const secondaryFor = (role: Role | null) => SECONDARY_NAV.filter((i) => !i.adminOnly || role === 'admin')

/** True when `href` is the page on screen (or a page under it). Works on v2 paths too. */
export function isCurrent(pathname: string, href: string) {
  const path = canonicalPath(pathname)
  return href === '/' ? path === '/' : path === href || path.startsWith(`${href}/`)
}
