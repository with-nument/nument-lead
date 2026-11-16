'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export const UNDO_MS = 30_000

export type PendingAction = {
  id: string
  /** What the inline row says, such as "Approved the reply to Maya Rao". */
  label: string
  /** Runs once the undo window closes (or right away when the page is left). */
  commit: () => Promise<void> | void
  /** Puts things back when Undo is pressed. */
  revert: () => void
}

type Entry = PendingAction & { deadline: number; timer: number }

/**
 * Optimistic actions with a 30 second Undo: the screen changes at once, the write waits until the window
 * closes. Leaving the page (navigation or closing the tab) commits whatever is still waiting, so an approval
 * is never lost; Undo is only offered while the page is open.
 */
export function useUndo(ms = UNDO_MS) {
  const [pending, setPending] = useState<Entry[]>([])
  const ref = useRef<Entry[]>([])
  const [now, setNow] = useState(() => Date.now())

  const remove = useCallback((id: string) => {
    ref.current = ref.current.filter((e) => e.id !== id)
    setPending(ref.current)
  }, [])

  const run = useCallback(
    (id: string) => {
      const entry = ref.current.find((e) => e.id === id)
      if (!entry) return
      window.clearTimeout(entry.timer)
      remove(id)
      void entry.commit()
    },
    [remove],
  )

  const schedule = useCallback(
    (action: PendingAction) => {
      const existing = ref.current.find((e) => e.id === action.id)
      if (existing) window.clearTimeout(existing.timer)
      const timer = window.setTimeout(() => run(action.id), ms)
      ref.current = [...ref.current.filter((e) => e.id !== action.id), { ...action, deadline: Date.now() + ms, timer }]
      setPending(ref.current)
      setNow(Date.now())
    },
    [ms, run],
  )

  const undo = useCallback(
    (id: string) => {
      const entry = ref.current.find((e) => e.id === id)
      if (!entry) return
      window.clearTimeout(entry.timer)
      remove(id)
      entry.revert()
    },
    [remove],
  )

  // A second tick for the countdown, only while something waits.
  useEffect(() => {
    if (!pending.length) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [pending.length])

  // Leaving the page commits everything still waiting.
  useEffect(() => {
    const flush = () => ref.current.map((e) => e.id).forEach(run)
    window.addEventListener('pagehide', flush)
    return () => {
      window.removeEventListener('pagehide', flush)
      flush()
    }
  }, [run])

  const secondsLeft = (e: Entry) => Math.max(0, Math.ceil((e.deadline - now) / 1000))
  return { pending, schedule, undo, commitNow: run, secondsLeft }
}
