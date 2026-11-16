'use client'

import { useId } from 'react'
import { cx } from '@/components/ui2/cx'

/**
 * One choice out of a few, looking like the segmented control but built on native radio inputs: arrow keys,
 * forms and screen readers work as they always do, and no extra JavaScript is downloaded (the Radix radio group
 * costs a few KB on pages that are close to their budget).
 */
export function Choice<T extends string>({
  items,
  value,
  onValueChange,
  label,
  name,
  className,
}: {
  items: readonly { value: T; label: string }[]
  value: T
  onValueChange: (value: T) => void
  label: string
  /** Form field name, when the choice is posted with a form. */
  name?: string
  className?: string
}) {
  const id = useId()
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx('grid h-9 rounded-control bg-fill-1 p-0.5 lg:h-8', className)}
      style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
    >
      {items.map((item) => (
        <label key={item.value} className="relative flex min-w-0 cursor-pointer">
          <input
            type="radio"
            name={name ?? id}
            value={item.value}
            checked={value === item.value}
            onChange={() => onValueChange(item.value)}
            className="peer absolute inset-0 cursor-pointer opacity-0"
          />
          <span
            className={cx(
              'pointer-events-none flex flex-1 items-center justify-center truncate rounded-[8px] px-3 text-[15px] font-medium text-label-2 transition-colors duration-[var(--ui-dur-1)] lg:text-[13px]',
              'peer-checked:bg-thumb peer-checked:font-semibold peer-checked:text-label-1 peer-checked:shadow-[var(--ui-shadow-thumb)] peer-focus-visible:outline-2 peer-focus-visible:outline-label-1',
            )}
          >
            {item.label}
          </span>
        </label>
      ))}
    </div>
  )
}
