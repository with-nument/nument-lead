import type { z } from 'zod'

/** What every Server Action returns. Messages are plain words, never raw database errors. */
export type ActionResult<T = undefined> =
  | { ok: true; message?: string; data?: T }
  | { ok: false; message: string; fieldErrors?: Record<string, string[] | undefined> }

export const ok = <T = undefined>(message?: string, data?: T): ActionResult<T> => ({ ok: true, message, data })
export const fail = (message: string, fieldErrors?: Record<string, string[] | undefined>): ActionResult<never> => ({
  ok: false,
  message,
  fieldErrors,
})

/** Field errors from a failed zod parse, keyed by field name. */
export function fieldErrorsOf(error: z.ZodError): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? '_')
    ;(out[key] ??= []).push(issue.message)
  }
  return out
}

export const SAVE_FAILED = 'Could not save. Try again.'
