'use client'

import { useEffect } from 'react'

/** How long an Undo row stays, in milliseconds. */
export const UNDO_MS = 30_000

/**
 * The inline Undo row that takes the place of something just removed. It stays 30 seconds, then calls
 * onExpire (the caller drops it). Undo calls onUndo, which puts the thing back.
 */
export function UndoRow({ message, onUndo, onExpire, pending }: { message: string; onUndo: () => void; onExpire: () => void; pending?: boolean }) {
  useEffect(() => {
    const t = window.setTimeout(onExpire, UNDO_MS)
    return () => window.clearTimeout(t)
  }, [onExpire])
  return (
    <div role="status" className="flex min-h-14 items-center gap-3 bg-fill-3 px-4 text-[15px] text-label-2 lg:px-5 lg:text-[14.5px]">
      <span className="min-w-0 flex-1 truncate">{message}</span>
      <button
        type="button"
        onClick={onUndo}
        disabled={pending}
        className="-my-2 shrink-0 rounded-[8px] px-2 py-2 font-semibold text-label-1 underline decoration-separator-strong underline-offset-4 hover:bg-fill-2 disabled:opacity-40"
      >
        Undo
      </button>
    </div>
  )
}
