import { cx } from './cx'
import { NavAccessory } from './nav-accessory'

/**
 * The page header: a large title that scrolls away under a translucent top bar, where a small title
 * then fades in (iOS and macOS). Pure CSS (scroll-driven animations); browsers without them keep the
 * bar's material on and simply skip the small title.
 */
export function LargeTitle({
  title,
  eyebrow,
  subtitle,
  actions,
  leading,
}: {
  title: string
  /** Quiet line above the title, such as today's date. */
  eyebrow?: React.ReactNode
  subtitle?: React.ReactNode
  /** Buttons at the trailing end of the top bar. */
  actions?: React.ReactNode
  /** A back link at the leading end of the top bar. */
  leading?: React.ReactNode
}) {
  return (
    <>
      <div className="navbar-material sticky top-0 z-20 pt-[env(safe-area-inset-top)]">
        <div className="relative mx-auto flex h-[var(--ui-navbar-h)] max-w-[1160px] items-center gap-2 px-4 sm:px-6 lg:px-10">
          <div className="flex min-w-0 flex-1 items-center">{leading}</div>
          <div aria-hidden className="navbar-title type-headline pointer-events-none absolute left-1/2 max-w-[50%] -translate-x-1/2 truncate">
            {title}
          </div>
          <div className="flex flex-1 items-center justify-end gap-2">
            {actions}
            <NavAccessory />
          </div>
        </div>
      </div>
      <header className="mx-auto max-w-[1160px] px-4 pt-1 pb-5 sm:px-6 lg:px-10 lg:pt-2 lg:pb-7">
        {eyebrow ? <p className="type-subhead mb-0.5 text-label-3">{eyebrow}</p> : null}
        <h1 className="type-large-title text-label-1">{title}</h1>
        {subtitle ? <p className="type-body mt-1 text-label-3">{subtitle}</p> : null}
      </header>
    </>
  )
}

/** A v2 page: the large title header, then the content in the page column. */
export function Page({
  children,
  className,
  ...header
}: React.ComponentProps<typeof LargeTitle> & { children: React.ReactNode; className?: string }) {
  return (
    <>
      <LargeTitle {...header} />
      <div className={cx('mx-auto max-w-[1160px] px-4 sm:px-6 lg:px-10', className)}>{children}</div>
    </>
  )
}
