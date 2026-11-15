import { requireUser } from '@/lib/auth'
import { initials } from '@/lib/format'
import { ROLE_LABEL } from '@/lib/roles'
import { AccountMenu, AccountSheet, type AccountView } from './account-controls'
import { SidebarLinks } from './sidebar-links'

async function accountView(): Promise<AccountView> {
  const user = await requireUser()
  return { initials: initials(user.name), role: user.role, roleLabel: ROLE_LABEL[user.role], email: user.email }
}

/** The role-aware sidebar links. The shell shows the everyone-list first; this streams in. */
export async function RoleSidebarLinks() {
  const user = await requireUser()
  return <SidebarLinks role={user.role} />
}

export async function SidebarAccount() {
  return <AccountMenu account={await accountView()} />
}

export async function PhoneAccount() {
  return <AccountSheet account={await accountView()} />
}
