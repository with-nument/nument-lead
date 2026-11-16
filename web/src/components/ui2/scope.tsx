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
//
// It also turns off React's 300 ms reveal batching for this page load. The prerendered shell (skeletons)
// paints at once and the per-user sections stream in about 100 ms later, but React's streaming runtime
// ($RC) holds every streamed section until 300 ms after the shell's first paint ($RT), so a full load showed
// skeletons for ~0.3 s even when the data was already there. With $RT never a number, the runtime reveals
// on the next animation frame instead (still batching what arrives in the same frame). The skeletons match
// the final layout, so nothing jumps. If a React upgrade changes this runtime the line does nothing and the
// default batching comes back (tests/unit/reveal-now.test.ts notices the change).
export const REVEAL_NOW = "Object.defineProperty(window,'$RT',{configurable:true,get:function(){},set:function(){}})"
const FIRST_PAINT = `document.documentElement.dataset.ui='2';${REVEAL_NOW}`
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
