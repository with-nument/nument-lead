'use client'

import { cx } from '@/components/ui2/cx'

/** An on/off switch (role="switch"): dark grey when on (only the primary button is solid black), a quiet grey when off. A 44 px tap target on phones. */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
}: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** Accessible name. */
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className="group -m-2.5 grid shrink-0 place-items-center p-2.5 disabled:opacity-40 lg:-m-1 lg:p-1"
    >
      <span
        className={cx(
          'relative block h-6 w-10 rounded-full transition-colors duration-[var(--ui-dur-1)]',
          checked ? 'bg-label-2' : 'bg-fill-1 group-hover:bg-fill-2',
        )}
      >
        <span
          aria-hidden
          className={cx(
            'absolute top-[3px] left-[3px] size-[18px] rounded-full bg-thumb shadow-[var(--ui-shadow-thumb)] transition-transform duration-[var(--ui-dur-2)] ease-glide motion-reduce:transition-none',
            checked && 'translate-x-4',
          )}
        />
      </span>
    </button>
  )
}
