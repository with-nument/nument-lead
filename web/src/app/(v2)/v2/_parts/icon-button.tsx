import { cx } from '@/components/ui2/cx'

/** A quiet grey icon button for row menus and remove: 44 px to tap on phones, 32 px with a mouse. */
export function IconButton({ className, type, ref, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { 'aria-label': string; ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={cx(
        '-mr-2 grid size-11 shrink-0 place-items-center rounded-control text-label-3 transition-colors duration-[var(--ui-dur-1)] hover:bg-fill-3 hover:text-label-1 disabled:opacity-40 lg:size-8 [&_svg]:size-[18px] lg:[&_svg]:size-4',
        className,
      )}
      {...props}
    />
  )
}
