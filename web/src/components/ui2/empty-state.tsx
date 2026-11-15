import { cx } from './cx'

/** Nothing here (yet): a quiet symbol, one title, one sentence, at most one action. */
export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon?: React.ReactNode
  title: React.ReactNode
  /** One calm sentence about what will appear here, or what to do. */
  children?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cx('flex flex-col items-center px-6 py-14 text-center lg:py-20', className)}>
      {icon ? (
        <div aria-hidden className="mb-4 text-label-3 [&_svg]:size-11 [&_svg]:stroke-[1.5]">
          {icon}
        </div>
      ) : null}
      <h2 className="type-title text-balance text-label-1">{title}</h2>
      {children ? <p className="type-body mt-2 max-w-[42ch] text-balance text-label-3">{children}</p> : null}
      {action ? <div className="mt-6 flex flex-wrap justify-center gap-3">{action}</div> : null}
    </div>
  )
}
