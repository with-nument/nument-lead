import { cx } from '@/components/ui2/cx'

/** Initials in a quiet circle. The shell never shows a person's name. */
export function Avatar({ initials, size = 'regular', className }: { initials: string; size?: 'regular' | 'large'; className?: string }) {
  return (
    <span
      aria-hidden
      className={cx(
        'grid shrink-0 place-items-center rounded-full bg-fill-1 font-semibold tracking-[0.02em] text-label-1',
        size === 'large' ? 'size-12 text-[17px]' : 'size-8 text-[13px]',
        className,
      )}
    >
      {initials}
    </span>
  )
}
