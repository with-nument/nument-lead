import { cache } from 'react'
import { requireUser } from '@/lib/auth'
import { initials } from '@/lib/format'
import { getNavCounts, type NavCounts } from '@/lib/queries/nav'
import { ROLE_LABEL } from '@/lib/roles'
import { LazyAccountMenu, LazyAccountSheet } from './account-lazy'
import type { AccountView } from './account-row'
import { SidebarLinks } from './sidebar-links'
import { TabBar } from './tab-bar'
import { CommandMenuHost } from './command-menu-host'

async function accountView(): Promise<AccountView> {
  const user = await requireUser()
  return { initials: initials(user.name), role: user.role, roleLabel: ROLE_LABEL[user.role], email: user.email }
}

/**
 * The navigation counts, once per request (the sidebar and the tab bar share them), or none when they cannot
 * be read: a missing number never breaks the shell.
 */
const navCounts = cache(async (): Promise<NavCounts | null> => {
  try {
    return await getNavCounts()
  } catch {
    return null
  }
})

/** The role-aware sidebar links with their counts. The shell shows the everyone-list first; this streams in. */
export async function RoleSidebarLinks() {
  const [user, counts] = await Promise.all([requireUser(), navCounts()])
  return <SidebarLinks role={user.role} counts={counts} />
}

/** The phone tab bar with the Inbox badge. The shell shows it without counts first. */
export async function CountedTabBar() {
  return <TabBar counts={await navCounts()} />
}

export async function SidebarAccount() {
  return <LazyAccountMenu account={await accountView()} />
}

export async function PhoneAccount() {
  return <LazyAccountSheet account={await accountView()} />
}

/** The ⌘K menu, with the pages this role may open. */
export async function RoleCommandMenu() {
  const user = await requireUser()
  return <CommandMenuHost role={user.role} />
}
