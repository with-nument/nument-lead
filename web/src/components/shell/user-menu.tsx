'use client'

import Link from 'next/link'
import { CircleHelp, LogOut, Settings } from 'lucide-react'
import { logout } from '@/app/(auth)/actions'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui/dropdown-menu'
import { initials } from '@/lib/format'
import { ROLE_LABEL, type Role } from '@/lib/roles'
import { requestTour } from '@/components/tour/tour-store'

export function UserMenu({ name, email, role }: { name: string; email: string; role: Role }) {
  return (
    <Menu>
      <MenuTrigger
        className="flex h-10 items-center gap-2 rounded-full pr-1 pl-1 text-left hover:bg-surface-2 data-[state=open]:bg-surface-2 sm:pr-3"
        aria-label={`Account menu for ${name}`}
      >
        <span className="grid size-8 place-items-center rounded-full bg-indigo-100 text-xs font-medium text-indigo-800">{initials(name)}</span>
        <span className="hidden min-w-0 flex-col leading-tight sm:flex">
          <span className="max-w-40 truncate text-sm text-tx-1">{name}</span>
          <span className="text-micro text-tx-3">{ROLE_LABEL[role]}</span>
        </span>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>Signed in as</MenuLabel>
        <div className="truncate px-2.5 pb-2 text-sm text-tx-2">{email}</div>
        <MenuSeparator />
        <MenuItem asChild>
          <Link href="/settings">
            <Settings aria-hidden />
            Profile and password
          </Link>
        </MenuItem>
        <MenuItem
          onSelect={() => {
            // Let the menu close and hand focus back first, then the tour takes it.
            window.setTimeout(requestTour, 0)
          }}
        >
          <CircleHelp aria-hidden />
          Take the tour
        </MenuItem>
        <MenuItem
          onSelect={() => {
            void logout()
          }}
        >
          <LogOut aria-hidden />
          Log out
        </MenuItem>
      </MenuContent>
    </Menu>
  )
}
