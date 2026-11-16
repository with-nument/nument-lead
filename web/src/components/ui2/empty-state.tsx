import { cx } from './cx'

/** Nothing here (yet): one title, one sentence on why and what next, at most one action. */
export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon?: React.ReactNode
  title: React.ReactNode
  /** One calm sentence about why it is empty and what to do. */
  children?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cx('flex flex-col items-center px-6 py-14 text-center lg:py-20', className)}>
      {icon ? (
        <div aria-hidden className="mb-4 text-label-3 [&_svg]:size-8 [&_svg]:stroke-[1.4]">
          {icon}
        </div>
      ) : null}
      <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-balance text-label-1">{title}</h2>
      {children ? <p className="type-body mt-2 max-w-[44ch] text-balance text-label-3">{children}</p> : null}
      {action ? <div className="mt-6 flex flex-wrap justify-center gap-3">{action}</div> : null}
    </div>
  )
}

/** A calm one-line empty state inside a list or a section: why it is empty and what comes next. */
export function EmptyLine({ children, action, className }: { children: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cx('flex min-h-14 items-center gap-4 px-4 py-3.5 text-[14px] text-label-3 lg:px-[22px]', className)}>
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  )
}
