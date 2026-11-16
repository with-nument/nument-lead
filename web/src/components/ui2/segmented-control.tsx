'use client'

import { RadioGroup } from 'radix-ui'
import { cx } from './cx'

export type Segment<T extends string> = {
  value: T
  label: React.ReactNode
  /** A quiet count after the label, such as the number of rows in that view. */
  count?: number
}

/**
 * One choice out of a few. A radio group underneath: arrow keys move and select. The selected segment is a
 * white chip on a grey track (mockups); segments size to their words.
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
  return (
    <RadioGroup.Root
      value={value}
      onValueChange={(v) => onValueChange(v as T)}
      aria-label={label}
      name={name}
      orientation="horizontal"
      loop
      className={cx('inline-flex max-w-full gap-0.5 overflow-x-auto rounded-control bg-fill-1 p-[3px]', className)}
    >
      {items.map((item) => (
        <RadioGroup.Item
          key={item.value}
          value={item.value}
          className={cx(
            'group inline-flex h-[38px] shrink-0 items-center gap-1.5 rounded-[9px] px-3.5 text-[14px] whitespace-nowrap transition-colors duration-[var(--ui-dur-1)] lg:h-8',
            'text-label-3 hover:text-label-1 focus-visible:outline-offset-0',
            'data-[state=checked]:bg-thumb data-[state=checked]:font-[550] data-[state=checked]:text-label-1 data-[state=checked]:shadow-[var(--ui-shadow-thumb)]',
          )}
        >
          {item.label}
          {item.count !== undefined ? <span className="text-[13px] font-normal text-label-3 tabular-nums">{item.count}</span> : null}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  )
}
