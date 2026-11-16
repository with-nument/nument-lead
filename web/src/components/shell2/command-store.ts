'use client'

import { useSyncExternalStore } from 'react'

// Whether the ⌘K command menu is open. A tiny store, so the sidebar search box, the phone search button and
// the keyboard shortcut can all open the one menu the layout renders.

let open = false
const listeners = new Set<() => void>()

export function setCommandMenuOpen(next: boolean) {
  if (open === next) return
  open = next
  listeners.forEach((l) => l())
}

export const openCommandMenu = () => setCommandMenuOpen(true)

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useCommandMenuOpen() {
  return useSyncExternalStore(
    subscribe,
    () => open,
    () => false,
  )
}
