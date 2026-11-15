import { cx } from './cx'

/** A soft placeholder block while content loads. Still for reduced motion. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cx('skeleton-2 block h-4 rounded-[6px]', className)} />
}

/** A grouped list's worth of placeholder rows. */
export function SkeletonList({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={cx('material-panel overflow-hidden rounded-panel', className)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex min-h-14 items-center gap-3 px-4 [&+&]:hairline-t">
          <Skeleton className="size-7 rounded-full" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
        </div>
      ))}
    </div>
  )
}
