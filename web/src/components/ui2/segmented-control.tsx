'use client'

import { RadioGroup } from 'radix-ui'
import { cx } from './cx'

export type Segment<T extends string> = { value: T; label: React.ReactNode }

/**
 * One choice out of a few (iOS and macOS segmented control). A radio group underneath: arrow keys move
 * and select, and the selected thumb slides (fades with reduced motion).
 */
export function SegmentedControl<T extends string>({
  items,
  value,
  onValueChange,
  label,
  name,
  className,
}: {
  items: readonly Segment<T>[]
  value: T
  onValueChange: (value: T) => void
  /** Accessible name of the group. */
  label: string
  /** Form field name, when the choice is posted with a form. */
  name?: string
  className?: string
}) {
  const index = Math.max(0, items.findIndex((i) => i.value === value))
  return (
    <RadioGroup.Root
      value={value}
      onValueChange={(v) => onValueChange(v as T)}
      aria-label={label}
      name={name}
      orientation="horizontal"
      loop
      className={cx('relative grid h-9 rounded-control bg-fill-1 p-0.5 lg:h-8', className)}
      style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0.5 left-0.5 rounded-[8px] bg-thumb shadow-[var(--ui-shadow-thumb)] transition-transform duration-[var(--ui-dur-2)] ease-glide motion-reduce:transition-none"
        style={{ width: `calc((100% - 4px) / ${items.length})`, transform: `translateX(${index * 100}%)` }}
      />
      {items.map((item) => (
        <RadioGroup.Item
          key={item.value}
          value={item.value}
          className={cx(
            'relative z-10 min-w-0 truncate rounded-[8px] px-3 text-[15px] font-medium transition-colors duration-[var(--ui-dur-1)] lg:text-[13px]',
            'text-label-2 data-[state=checked]:text-label-1 data-[state=checked]:font-semibold focus-visible:outline-offset-0',
          )}
        >
          {item.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  )
}
