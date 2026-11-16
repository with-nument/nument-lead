'use client'

import { useActionState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from '@/components/ui2/toast'
import type { ActionResult } from '@/lib/action-result'

type Options<T> = { onOk?: (r: Extract<ActionResult<T>, { ok: true }>) => void; onFail?: () => void; quiet?: boolean }

/**
 * Runs a Server Action from a button: a short toast with its message, a fresh page on success (the v2 pages
 * render at their normal URLs, which the classic actions do not revalidate), and onFail to roll back an
 * optimistic change.
 */
export function useRun() {
  const router = useRouter()
  const [pending, start] = useTransition()
  function run<T>(fn: () => Promise<ActionResult<T>>, opts: Options<T> = {}) {
    start(async () => {
      let r: ActionResult<T>
      try {
        r = await fn()
      } catch {
        r = { ok: false, message: 'Could not reach the server. Check the connection and try again.' }
      }
      if (r.ok) {
        if (!opts.quiet && r.message) toast(r.message)
        opts.onOk?.(r)
        router.refresh()
      } else {
        toast.error(r.message)
        opts.onFail?.()
      }
    })
  }
  return [pending, run] as const
}

/**
 * A form's Server Action for useActionState: a toast with its message and a fresh page on success, then
 * onOk (close the sheet). The result stays in state for field errors.
 */
export function useFormAction<T = undefined>(
  fn: (prev: unknown, fd: FormData) => Promise<ActionResult<T>>,
  onOk?: (r: Extract<ActionResult<T>, { ok: true }>) => void,
  opts: { quiet?: boolean } = {},
) {
  const router = useRouter()
  return useActionState(async (prev: ActionResult<T> | undefined, fd: FormData) => {
    const r = await fn(prev, fd)
    if (r.ok) {
      if (!opts.quiet) toast(r.message ?? 'Saved')
      onOk?.(r)
      router.refresh()
    }
    return r
  }, undefined)
}
