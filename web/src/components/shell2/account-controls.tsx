'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import { ChevronsUpDown, LogOut, Undo2 } from 'lucide-react'
import { logout } from '@/app/(auth)/actions'
import { GroupedList, ListRow } from '@/components/ui2/grouped-list'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui2/sheet'
import type { Role } from '@/lib/roles'
import { switchDesign } from '@/lib/ui-flag'
import { Avatar } from './avatar'
import { secondaryFor } from './nav-items'

export type AccountView = { initials: string; role: Role; roleLabel: string; email: string }

/** Laptop: the account row at the foot of the sidebar, with a small menu. */
export function AccountMenu({ account }: { account: AccountView }) {
  return (
    <Menu>
      <MenuTrigger
        aria-label="Account"
        className="flex h-11 w-full items-center gap-2.5 rounded-[10px] px-2 text-left transition-colors hover:bg-fill-3 data-[state=open]:bg-fill-2"
      >
        <Avatar initials={account.initials} />
        <span className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="text-[13px] font-semibold text-label-1">Account</span>
          <span className="type-caption text-label-3">{account.roleLabel}</span>
        </span>
        <ChevronsUpDown aria-hidden className="size-4 text-label-3" />
      </MenuTrigger>
      <MenuContent side="top" align="start" className="w-[232px]">
        <MenuLabel>
          <span className="block truncate">{account.email}</span>
        </MenuLabel>
        <MenuSeparator />
        <MenuItem onSelect={() => switchDesign(false)}>
          <Undo2 aria-hidden />
          Use the classic design
        </MenuItem>
        <MenuItem
          onSelect={() => {
            void logout()
          }}
        >
          <LogOut aria-hidden />
          Sign out
        </MenuItem>
      </MenuContent>
    </Menu>
  )
}

/** Phones and tablets: the avatar in the top bar opens a sheet with everything not in the tab bar. */
export function AccountSheet({ account }: { account: AccountView }) {
  const path = usePathname()
  // Open for the page it was opened on, so following a link closes it without an effect.
  const [openOn, setOpenOn] = useState<string | null>(null)
  return (
    <Sheet open={openOn === path} onOpenChange={(open) => setOpenOn(open ? path : null)}>
      <SheetTrigger aria-label="Account" className="-mr-1 grid size-11 place-items-center rounded-full lg:hidden">
        <Avatar initials={account.initials} />
      </SheetTrigger>
      <SheetContent title="Account">
        <div className="flex flex-col gap-6">
          <div className="flex items-center gap-3 px-1">
            <Avatar initials={account.initials} size="large" />
            <div className="min-w-0">
              <p className="type-headline text-label-1">{account.roleLabel}</p>
              <p className="type-subhead truncate text-label-3">{account.email}</p>
            </div>
          </div>
          <GroupedList label="More">
            {secondaryFor(account.role).map((item) => {
              const Icon = item.icon
              return <ListRow key={item.href} href={item.href} icon={<Icon />} title={item.label} />
            })}
          </GroupedList>
          <GroupedList label="Design" footer="Pages that are not redesigned yet open in the classic design.">
            <ListRow onClick={() => switchDesign(false)} title="Use the classic design" tone="accent" />
          </GroupedList>
          <GroupedList label="Session">
            <ListRow
              onClick={() => {
                void logout()
              }}
              title="Sign out"
              tone="destructive"
            />
          </GroupedList>
        </div>
      </SheetContent>
    </Sheet>
  )
}
