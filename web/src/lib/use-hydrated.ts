'use client'

import { useSyncExternalStore } from 'react'

const subscribe = () => () => {}

/**
 * False during server rendering and hydration, true once React runs in the browser.
 * Submit buttons stay disabled until then: with partial prerendering, a form posted before
 * hydration would get the cached page shell back instead of running its Server Action.
 */
export function useHydrated() {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  )
}
