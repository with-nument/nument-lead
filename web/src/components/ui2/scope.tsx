'use client'

import { useLayoutEffect, useSyncExternalStore } from 'react'

// Which design the page on screen uses. The v2 layouts (new design, sign-in) render <V2Scope />.
// While one is mounted, <html data-ui="2"> turns on the v2 canvas (theme.css), and useInV2() keeps
// sonner off. The router keeps recently visited pages mounted but hidden; a hidden page runs no
// effects, so a hidden v2 page never restyles the current-design page on screen.

let mounted = 0
const listeners = new Set<() => void>()
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

function sync() {
  if (mounted > 0) document.documentElement.dataset.ui = '2'
  else delete document.documentElement.dataset.ui
  listeners.forEach((l) => l())
}

// For the first paint of a full page load, before React runs.
const FIRST_PAINT = "document.documentElement.dataset.ui='2'"
const never = () => () => {}

/** Marks the page as new design while it is on screen. */
export function V2Scope() {
  // The script is only part of server HTML (true while hydrating it); a page mounted by client
  // navigation renders none, since the browser would not run it anyway. The effect covers that case.
  const fromServer = useSyncExternalStore(
    never,
    () => false,
    () => true,
  )
  useLayoutEffect(() => {
    mounted++
    sync()
    return () => {
      mounted--
      sync()
    }
  }, [])
  return fromServer ? <script dangerouslySetInnerHTML={{ __html: FIRST_PAINT }} /> : null
}

/** True while a new-design page is on screen. True on the server, so nothing extra renders there. */
export function useInV2() {
  return useSyncExternalStore(
    subscribe,
    () => mounted > 0,
    () => true,
  )
}
