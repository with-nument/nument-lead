'use client'

import { createContext, useContext } from 'react'

/**
 * A slot at the trailing end of every page's top bar. The app shell fills it (the account button on
 * phones), so pages never have to remember it and ui2 never depends on the shell.
 */
const NavAccessoryContext = createContext<React.ReactNode>(null)

export function NavAccessoryProvider({ value, children }: { value: React.ReactNode; children: React.ReactNode }) {
  return <NavAccessoryContext value={value}>{children}</NavAccessoryContext>
}

export function NavAccessory() {
  return useContext(NavAccessoryContext)
}
