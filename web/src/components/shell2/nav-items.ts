import type { Role } from '@/lib/roles'
import type { NavCounts } from '@/lib/queries/page-data'
import { canonicalPath } from '@/lib/ui-flag'
import { CallsIcon, DealsIcon, EngineIcon, InboxIcon, InsightsIcon, LeadsIcon, SettingsIcon, TodayIcon, type NavIcon } from './icons'

export type NavItem = { href: string; label: string; icon: NavIcon; adminOnly?: boolean }

/** The five places people work in: the sidebar on laptops, the tab bar on phones. */
export const PRIMARY_NAV: readonly NavItem[] = [
  { href: '/', label: 'Today', icon: TodayIcon },
  { href: '/inbox', label: 'Inbox', icon: InboxIcon },
  { href: '/calls', label: 'Calls', icon: CallsIcon },
  { href: '/deals', label: 'Deals', icon: DealsIcon },
  { href: '/leads', label: 'Leads', icon: LeadsIcon },
]

/** Everything else: at the foot of the sidebar, in the account sheet on phones. */
export const SECONDARY_NAV: readonly NavItem[] = [
  { href: '/insights', label: 'Insights', icon: InsightsIcon },
  { href: '/engine', label: 'Engine', icon: EngineIcon, adminOnly: true },
  { href: '/settings', label: 'Settings', icon: SettingsIcon },
]

/** Secondary items this role may open. Before the role is known, only the ones everyone has. */
export const secondaryFor = (role: Role | null) => SECONDARY_NAV.filter((i) => !i.adminOnly || role === 'admin')

/** True when `href` is the page on screen (or a page under it). Works on v2 paths too. */
export function isCurrent(pathname: string, href: string) {
  const path = canonicalPath(pathname)
  return href === '/' ? path === '/' : path === href || path.startsWith(`${href}/`)
}

/**
 * The small number beside a place, or null for none. Today counts what needs a person today the way the Today
 * page does: each follow-up due, plus one for the batch of new startups ready to contact. Calls and Leads have
 * no count until their data exists.
 */
export function navCount(href: string, counts: NavCounts | null | undefined): number | null {
  if (!counts) return null
  const n =
    href === '/'
      ? counts.followupsDue + (counts.ready > 0 ? 1 : 0)
      : href === '/inbox'
        ? counts.inboxNew
        : href === '/deals'
          ? counts.deals
          : 0
  return n > 0 ? n : null
}
