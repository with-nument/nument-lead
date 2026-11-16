'use client'

import { Kbd } from '@/components/ui2/button'
import { openCommandMenu } from './command-store'
import { SearchIcon } from './icons'

/** The sidebar search box: opens the command menu (also ⌘K). */
export function SidebarSearch() {
  return (
    <button
      type="button"
      onClick={openCommandMenu}
      aria-keyshortcuts="Meta+K Control+K"
      className="flex h-10 w-full items-center gap-2.5 rounded-control border border-separator bg-field px-3 text-[14px] text-label-3 transition-colors hover:border-separator-strong"
    >
      <SearchIcon className="size-4 shrink-0" />
      <span className="flex-1 text-left">Search</span>
      <Kbd>⌘K</Kbd>
    </button>
  )
}

/** The search button in the phone top bar. */
export function PhoneSearchButton() {
  return (
    <button type="button" onClick={openCommandMenu} aria-label="Search" className="grid size-11 place-items-center rounded-full text-label-1 lg:hidden">
      <SearchIcon className="size-[22px]" />
    </button>
  )
}
