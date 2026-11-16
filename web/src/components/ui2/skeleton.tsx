import { cx } from './cx'

/** A soft placeholder block while content loads. Still for reduced motion. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cx('skeleton-2 block h-4 rounded-[6px]', className)} />
}

/** A surface of placeholder rows shaped like the list that replaces it: avatar, two lines, a button. */
export function SkeletonList({ rows = 4, header = false, action = false, className }: { rows?: number; header?: boolean; action?: boolean; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={cx('material-panel overflow-hidden rounded-panel', className)}>
      {header ? (
        <div className="flex items-center gap-3 px-4 pt-[15px] pb-[13px] lg:px-[22px]">
          <Skeleton className="size-6 rounded-full" />
          <Skeleton className="h-4 w-36" />
        </div>
      ) : null}
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={cx('flex min-h-[72px] items-center gap-4 px-4 lg:px-[22px]', (i > 0 || header) && 'hairline-t')}>
          <Skeleton className="size-9 rounded-full max-lg:hidden" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          {action ? <Skeleton className="h-[38px] w-32 rounded-control max-lg:hidden" /> : null}
        </div>
      ))}
    </div>
  )
}
