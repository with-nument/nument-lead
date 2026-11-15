'use client'

import { useSyncExternalStore } from 'react'
import { CircleAlert, CircleCheck } from 'lucide-react'
import { cx } from './cx'

// A tiny toast (a few hundred bytes): a short confirmation after an action, announced politely.
// v2 pages use this; sonner stays with the current design until it is retired.

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
          className="motion-toast material-overlay type-body pointer-events-auto flex w-full max-w-[400px] items-center gap-3 rounded-panel py-3 pr-3 pl-4 text-label-1"
        >
          {t.tone === 'ok' ? <CircleCheck aria-hidden className="size-5 shrink-0 text-status-ok" /> : null}
          {t.tone === 'bad' ? <CircleAlert aria-hidden className="size-5 shrink-0 text-status-bad" /> : null}
          <span className="min-w-0 flex-1">{t.message}</span>
          {t.action ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                t.action?.onClick()
                dismiss(t.id)
              }}
              className={cx('shrink-0 rounded-[8px] px-2 py-1 font-semibold text-accent hover:bg-fill-3')}
            >
              {t.action.label}
            </button>
          ) : null}
        </div>
      ))}
    </div>
  )
}
