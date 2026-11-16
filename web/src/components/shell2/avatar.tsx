import { cx } from '@/components/ui2/cx'

/** Initials in a quiet grey circle. The shell never shows a person's name. */
export function Avatar({ initials, size = 'regular', className }: { initials: string; size?: 'regular' | 'large'; className?: string }) {
  return (
    <span
      aria-hidden
      className={cx(
        'grid shrink-0 place-items-center rounded-full border border-separator bg-avatar font-semibold tracking-[0.01em] text-label-2',
        size === 'large' ? 'size-11 text-[14px]' : 'size-7 text-[11px]',
        className,
      )}
    >
      {initials}
    </span>
  )
}
