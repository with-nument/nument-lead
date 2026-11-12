'use client'

import { startTransition, useEffect } from 'react'
import { useRouter } from 'next/navigation'

/** Something the person is in the middle of: typing in a field, or a dialog, menu or the tour is open. */
function busy() {
  const el = document.activeElement as HTMLElement | null
  if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return true
  return Boolean(document.querySelector('[role="dialog"], [role="alertdialog"], [role="menu"], dialog[open], [data-testid="tour"]'))
}

/**
 * Quietly brings the page up to date with what teammates and the engine changed (plan 15.5.5), without
 * ever feeling like a reload: at most once every `minutes`, while the tab is visible, and right away
 * when someone comes back after being away that long. Never while they type or have a dialog open.
 * router.refresh() re-renders on the server and merges the result in a transition, so scroll position,
 * open rows and other client state stay as they were.
 */
export function AutoRefresh({ minutes = 5 }: { minutes?: number }) {
  const router = useRouter()
  useEffect(() => {
    const gap = minutes * 60_000
    let last = Date.now()
    let awaySince: number | null = null
    const refresh = () => {
      if (document.visibilityState !== 'visible' || busy() || Date.now() - last < gap) return
      last = Date.now()
      startTransition(() => router.refresh())
    }
    const timer = window.setInterval(refresh, gap)
    const onAway = () => {
      awaySince ??= Date.now()
    }
    const onBack = () => {
      if (document.visibilityState !== 'visible') return onAway()
      const away = awaySince === null ? 0 : Date.now() - awaySince
      awaySince = null
      if (away >= gap) refresh()
    }
    window.addEventListener('blur', onAway)
    window.addEventListener('focus', onBack)
    document.addEventListener('visibilitychange', onBack)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('blur', onAway)
      window.removeEventListener('focus', onBack)
      document.removeEventListener('visibilitychange', onBack)
    }
  }, [router, minutes])
  return null
}
