'use client'

import { lazy, Suspense, useSyncExternalStore } from 'react'
import { tourStorageKey } from '@/lib/tour'

// The sheet's code (dialog, artwork, copy) downloads only for someone who has not seen it.
const WelcomeSheet = lazy(() => import('./welcome').then((m) => ({ default: m.WelcomeSheet })))

const noop = () => () => {}

function seenHere(userId: string) {
  try {
    return window.localStorage.getItem(tourStorageKey(userId)) !== null
  } catch {
    return false
  }
}

/**
 * Opens the welcome sheet (mockup 08) once, on the first visit to the new Today. It replaces the old product tour
 * for the new design and shares its "done" mark, so finishing either one hides both.
 */
export function WelcomeGate({ userId, completedAt }: { userId: string; completedAt: string | null }) {
  // The server snapshot says "seen" so nothing opens before the browser has checked localStorage.
  const seen = useSyncExternalStore(
    noop,
    () => completedAt !== null || seenHere(userId),
    () => true,
  )
  if (seen) return null
  return (
    <Suspense fallback={null}>
      <WelcomeSheet userId={userId} />
    </Suspense>
  )
}
