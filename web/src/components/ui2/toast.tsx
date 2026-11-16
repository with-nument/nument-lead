'use client'

import { useSyncExternalStore } from 'react'
import { CircleAlert, CircleCheck } from 'lucide-react'
import { cx } from './cx'

// A tiny toast (a few hundred bytes), for errors and confirmations that have no row to sit in.
// Changes that can be taken back use the inline Undo row (undo-row.tsx) instead.

type Tone = 'neutral' | 'ok' | 'bad'
type Action = { label: string; onClick: () => void }
type Item = { id: number; message: string; tone: Tone; action?: Action }
type Options = { action?: Action; duration?: number }

let items: readonly Item[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
const NONE: readonly Item[] = []

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id)
  emit()
}

function add(message: string, tone: Tone, options?: Options) {
  const id = nextId++
  items = [...items, { id, message, tone, action: options?.action }].slice(-3)
  emit()
  window.setTimeout(() => dismiss(id), options?.duration ?? (options?.action ? 6000 : 4000))
  return id
}

export const toast = Object.assign((message: string, options?: Options) => add(message, 'neutral', options), {
  success: (message: string, options?: Options) => add(message, 'ok', options),
  error: (message: string, options?: Options) => add(message, 'bad', options),
  dismiss,
})

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** Where toasts appear: above the tab bar on phones, bottom right on laptops. Render once per layout. */
export function Toaster() {
  const list = useSyncExternalStore(
    subscribe,
    () => items,
    () => NONE,
  )
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--ui-tabbar-h)+env(safe-area-inset-bottom)+12px)] z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6 lg:items-end lg:px-6"
    >
      {list.map((t) => (
        <div
          key={t.id}
          data-ui-motion
          onClick={() => dismiss(t.id)}
          className="motion-toast material-overlay pointer-events-auto flex w-full max-w-[400px] items-center gap-3 rounded-[14px] py-3 pr-3 pl-4 text-[14px] text-label-1"
        >
          {t.tone === 'ok' ? <CircleCheck aria-hidden className="size-[18px] shrink-0 text-status-ok" strokeWidth={1.6} /> : null}
          {t.tone === 'bad' ? <CircleAlert aria-hidden className="size-[18px] shrink-0 text-status-bad" strokeWidth={1.6} /> : null}
          <span className="min-w-0 flex-1">{t.message}</span>
          {t.action ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                t.action?.onClick()
                dismiss(t.id)
              }}
              className={cx('shrink-0 rounded-[8px] px-2 py-1 text-label-1 underline decoration-separator-strong underline-offset-[3px] hover:bg-fill-3')}
            >
              {t.action.label}
            </button>
          ) : null}
        </div>
      ))}
    </div>
  )
}
