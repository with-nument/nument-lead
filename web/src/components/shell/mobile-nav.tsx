'use client'

import { useState } from 'react'
import { Menu as MenuIcon } from 'lucide-react'
import { Drawer, DrawerContent, DrawerTrigger } from '@/components/ui/drawer'
import { Logo } from '@/components/brand/logo'
import type { Role } from '@/lib/roles'
import { NavLinks } from './nav'

export function MobileNav({ role }: { role: Role }) {
  const [open, setOpen] = useState(false)
  return (
    <Drawer open={open} onOpenChange={setOpen}>
      <DrawerTrigger className="-ml-2 grid size-10 place-items-center rounded-full text-tx-2 hover:bg-surface-2 lg:hidden" aria-label="Open menu">
        <MenuIcon className="size-5" strokeWidth={1.75} />
      </DrawerTrigger>
      <DrawerContent title="Menu" side="left">
        <div className="p-4">
          <div className="mb-4 px-3">
            <Logo />
          </div>
          <NavLinks role={role} onNavigate={() => setOpen(false)} />
        </div>
      </DrawerContent>
    </Drawer>
  )
}
