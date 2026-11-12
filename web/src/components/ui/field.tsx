import { useId } from 'react'
import { cn } from '@/lib/cn'

type FieldProps = {
  label: React.ReactNode
  hint?: React.ReactNode
  error?: string | string[] | null
  className?: string
  /** Visually hide the label (it stays for screen readers). */
  hideLabel?: boolean
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => React.ReactNode
}

/** Label, control, hint and error, wired together with aria-describedby (plan 15.8.2). */
export function Field({ label, hint, error, className, hideLabel, children }: FieldProps) {
  const id = useId()
  const errors = (Array.isArray(error) ? error : error ? [error] : []).filter(Boolean)
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = errors.length ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label htmlFor={id} className={cn('text-sm font-medium text-tx-2', hideLabel && 'sr-only')}>
        {label}
      </label>
      {children({ id, describedBy, invalid: errors.length > 0 })}
      {hint && !errors.length ? (
        <p id={hintId} className="text-xs text-tx-3">
          {hint}
        </p>
      ) : null}
      {errors.length ? (
        <p id={errorId} className="text-xs text-bad">
          {errors[0]}
        </p>
      ) : null}
    </div>
  )
}
