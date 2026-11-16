'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check } from 'lucide-react'
import { cx } from './cx'

/** How long an Undo row stays (mockups: "Sending in 24 s"). */
export const UNDO_SECONDS = 30

/**
 * Something just done, that can still be taken back. Either the change is already saved and `undo` reverses
 * it, or (`commit` given) the change waits: it is saved when the row runs out, when the page is left, or never
 * if Undo is pressed.
 */
export type PendingChange = {
  id: string
  /** What happened, in plain words: "Marked Fieldnote as contacted". */
  message: string
  /** The countdown words before the seconds: "Sending in" or "Undo for". */
  countdown?: string
  expiresAt: number
  /** Reverses a change that is already saved. */
  undo?: () => void | Promise<void>
  /** Saves a waiting change. */
  commit?: () => void | Promise<void>
}

/**
 * Keeps the Undo rows of one list. Waiting changes are saved when their time runs out, and all of them at once
 * when the list unmounts or the tab is hidden, so nothing is lost by leaving the page.
 */
export function useUndoQueue() {
  const [items, setItems] = useState<PendingChange[]>([])
  const live = useRef(new Map<string, PendingChange>())

  const settle = useCallback((id: string, how: 'expire' | 'undo') => {
    const item = live.current.get(id)
    if (!item) return
    live.current.delete(id)
    setItems((list) => list.filter((i) => i.id !== id))
    if (how === 'undo') void item.undo?.()
    else void item.commit?.()
  }, [])

  const push = useCallback(
    (change: Omit<PendingChange, 'expiresAt'> & { seconds?: number }) => {
      const { seconds = UNDO_SECONDS, ...rest } = change
      const item: PendingChange = { ...rest, expiresAt: Date.now() + seconds * 1000 }
      // A newer change for the same thing replaces the older one (which is settled first).
      if (live.current.has(item.id)) settle(item.id, 'expire')
      live.current.set(item.id, item)
      setItems((list) => [...list.filter((i) => i.id !== item.id), item])
      window.setTimeout(() => settle(item.id, 'expire'), seconds * 1000)
    },
    [settle],
  )

  useEffect(() => {
    const map = live.current
    const flush = () => {
      for (const id of [...map.keys()]) {
        const item = map.get(id)
        if (item?.commit) {
          map.delete(id)
          void item.commit()
        }
      }
    }
    const onHide = () => {
      if (document.visibilityState === 'hidden') flush()
    }
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      flush()
    }
  }, [])

  return { items, push, undo: (id: string) => settle(id, 'undo'), has: (id: string) => items.some((i) => i.id === id) }
}

function useSecondsLeft(expiresAt: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  return Math.max(0, Math.ceil((expiresAt - now) / 1000))
}

/** The inline Undo row (mockups): a tick, what happened, the countdown and Undo. */
export function UndoRow({ change, onUndo, className }: { change: PendingChange; onUndo: () => void; className?: string }) {
  const left = useSecondsLeft(change.expiresAt)
  return (
    <div
      role="status"
      className={cx('flex min-h-14 items-center gap-3 bg-row-done px-4 py-3 text-[14px] text-label-3 lg:gap-4 lg:px-[22px]', className)}
    >
      <Check aria-hidden className="size-4 shrink-0" strokeWidth={1.6} />
      <span className="min-w-0 flex-1 truncate">{change.message}</span>
      <span className="type-caption hidden shrink-0 tabular-nums text-label-3 sm:inline" suppressHydrationWarning>
        {change.countdown ?? 'Undo for'} {left} s
      </span>
      <button
        type="button"
        onClick={onUndo}
        className="-my-2 -mr-2 inline-flex min-h-11 shrink-0 items-center px-2 text-[14px] text-label-1 underline decoration-separator-strong underline-offset-[3px] hover:decoration-label-1 lg:min-h-8"
      >
        Undo
      </button>
    </div>
  )
}
