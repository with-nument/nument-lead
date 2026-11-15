import { cx } from './cx'

/**
 * Text fields grouped in one rounded block (iOS): each row has its label on the left and the field on
 * the right, labels aligned to the widest one. Rows are separated by a hairline.
 */
export function FieldGroup({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx('grid grid-cols-[auto_minmax(0,1fr)] rounded-panel bg-field hairline-ring', className)}>{children}</div>
}

export function FieldRow({
  label,
  htmlFor,
  children,
  trailing,
}: {
  label: string
  htmlFor: string
  /** The input. Give it `fieldInput` classes. */
  children: React.ReactNode
  /** A small control after the field, such as show password. */
  trailing?: React.ReactNode
}) {
  return (
    <div
      className={cx(
        'relative col-span-2 grid grid-cols-subgrid items-center first:rounded-t-panel last:rounded-b-panel',
        'transition-shadow duration-[var(--ui-dur-1)] focus-within:shadow-[inset_0_0_0_2px_var(--ui-accent)]',
        'after:pointer-events-none after:absolute after:right-0 after:bottom-0 after:left-4 after:h-[var(--ui-hairline)] after:bg-separator last:after:hidden',
      )}
    >
      <label htmlFor={htmlFor} className="type-body cursor-text py-3 pr-3 pl-4 whitespace-nowrap text-label-1">
        {label}
      </label>
      <div className="flex min-w-0 items-center gap-1 pr-2">
        {children}
        {trailing}
      </div>
    </div>
  )
}

/** Classes for an input inside a FieldRow: borderless, the row shows focus. */
export const fieldInput =
  'type-body h-12 w-full min-w-0 bg-transparent py-0 pr-2 text-label-1 outline-none focus-visible:outline-none placeholder:text-label-4 lg:h-11'
