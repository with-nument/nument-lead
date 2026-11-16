'use client'

import { useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import type { Role } from '@/lib/roles'
import { setCommandMenuOpen, useCommandMenuOpen } from './command-store'

// The menu (dialog, search, results) downloads the first time it opens, not with every page.
const CommandMenu = dynamic(() => import('./command-menu').then((m) => m.CommandMenu), { ssr: false })

/** Listens for ⌘K / Ctrl+K everywhere and mounts the command menu once it is first asked for. */
export function CommandMenuHost({ role = null }: { role?: Role | null }) {
  const open = useCommandMenuOpen()
  const [wanted, setWanted] = useState(false)
  if (open && !wanted) setWanted(true)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommandMenuOpen(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return wanted ? <CommandMenu role={role} /> : null
}
