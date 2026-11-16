'use client'

import { useCallback, useEffect, useRef, useState, useTransition } from 'react'
import { toast } from '@/components/ui2/toast'
import { cx } from '@/components/ui2/cx'

type Result = { ok: boolean; message?: string }

/** Runs a server action in a transition: a short toast when it saves, the reason when it does not. */
export function useRun() {
  const [pending, start] = useTransition()
  const run = (fn: () => Promise<Result>, onOk?: () => void, opts: { quiet?: boolean } = {}) =>
    start(async () => {
      const r = await fn()
      if (r.ok) {
        if (!opts.quiet) toast(r.message ?? 'Saved')
        onOk?.()
      } else toast.error(r.message ?? 'Could not save. Try again.')
    })
  return { pending, run }
}

export const UNDO_MS = 30_000

type UndoItem = { id: number; text: string; undo: () => Promise<Result>; at: number }

/**
 * The inline Undo row: after an optimistic action, one quiet line says what happened, with Undo for 30
 * seconds. A newer action replaces it.
 */
export function useUndo() {
  const [item, setItem] = useState<UndoItem | null>(null)
  const seq = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const clear = useCallback(() => setItem(null), [])
  const offer = useCallback((text: string, undo: () => Promise<Result>) => {
    const id = ++seq.current
    setItem({ id, text, undo, at: Date.now() })
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setItem((cur) => (cur?.id === id ? null : cur)), UNDO_MS)
  }, [])
  return { item, offer, clear }
}

export function UndoRow({ undo, className, onUndone }: { undo: ReturnType<typeof useUndo>; className?: string; onUndone?: () => void }) {
  const [pending, start] = useTransition()
  const { item, clear } = undo
  if (!item) return null
  return (
    <div role="status" className={cx('flex min-h-11 items-center gap-3 rounded-control bg-fill-3 px-4 type-body text-label-2 lg:min-h-10', className)}>
      <span className="min-w-0 flex-1 truncate">{item.text}</span>
      <button
        type="button"
        disabled={pending}
        onClick={() =>
          start(async () => {
            const r = await item.undo()
            if (r.ok) {
              toast(r.message ?? 'Undone')
              clear()
              onUndone?.()
            } else toast.error(r.message ?? 'Could not undo. Try again.')
          })
        }
        className="-mr-2 h-9 shrink-0 rounded-[8px] px-3 font-semibold text-label-1 underline decoration-separator-strong underline-offset-4 hover:bg-fill-2 disabled:opacity-40"
      >
        Undo
      </button>
      <button type="button" onClick={clear} aria-label="Dismiss" className="-mr-2 h-9 shrink-0 rounded-[8px] px-2 text-label-3 hover:bg-fill-2">
        Dismiss
      </button>
    </div>
  )
}
