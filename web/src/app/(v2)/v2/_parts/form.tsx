'use client'

import { useId } from 'react'
import { Button } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { useHydrated } from '@/lib/use-hydrated'

// Small form pieces for the sheets on the Settings and Engine pages: a labelled field with its error, and
// the submit button (disabled until hydrated, so a form never posts to a prerendered shell).

const fieldBase =
  'w-full min-w-0 rounded-control bg-fill-1 px-3 text-[17px] text-label-1 outline-none placeholder:text-label-4 lg:text-[15px] ' +
  'focus-visible:shadow-[inset_0_0_0_1.5px_var(--ui-label-1)] aria-invalid:shadow-[inset_0_0_0_1.5px_var(--ui-bad)] disabled:opacity-60'

export const inputClass = `h-11 lg:h-10 ${fieldBase}`
export const textareaClass = `py-2.5 ${fieldBase}`

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string
  hint?: string
  error?: string[] | string
  children: (p: { id: string; describedBy?: string; invalid: boolean }) => React.ReactNode
  className?: string
}) {
  const id = useId()
  const msg = Array.isArray(error) ? error[0] : error
  const describedBy = msg ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className={cx('flex flex-col gap-1.5', className)}>
      <label htmlFor={id} className="type-subhead font-medium text-label-2 lg:text-[13px]">
        {label}
      </label>
      {children({ id, describedBy, invalid: Boolean(msg) })}
      {msg ? (
        <p id={`${id}-error`} className="type-caption text-status-bad">
          {msg}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="type-caption text-label-3">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

export function Submit({ children, pending, primary = true }: { children: React.ReactNode; pending?: boolean; primary?: boolean }) {
  const hydrated = useHydrated()
  return (
    <Button type="submit" variant={primary ? 'primary' : 'secondary'} disabled={!hydrated || pending} aria-busy={pending || undefined} data-hydrating={hydrated ? undefined : ''}>
      {children}
    </Button>
  )
}

/** A form-level message when the action failed without field errors. */
export function FormError({ message }: { message?: string }) {
  return message ? (
    <p role="alert" className="type-subhead text-status-bad">
      {message}
    </p>
  ) : null
}
