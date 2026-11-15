import { ChevronsUpDown } from 'lucide-react'
import { cx } from './cx'

/**
 * A native select, styled. The phone shows its own picker, keyboard and screen readers work as they
 * always do, and nothing extra is downloaded.
 */
export function Select({
  className,
  children,
  ref,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { ref?: React.Ref<HTMLSelectElement> }) {
  return (
    <span className={cx('relative inline-flex min-w-0', className)}>
      <select
        ref={ref}
        className={cx(
          'h-11 w-full min-w-0 cursor-pointer appearance-none truncate rounded-control bg-fill-1 py-0 pr-9 pl-3 text-[17px] text-label-1 lg:h-9 lg:text-[15px]',
          'transition-colors duration-[var(--ui-dur-1)] hover:bg-fill-2 disabled:cursor-default disabled:opacity-40 aria-invalid:shadow-[inset_0_0_0_1.5px_var(--ui-bad)]',
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronsUpDown aria-hidden className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-label-3" strokeWidth={2.25} />
    </span>
  )
}
