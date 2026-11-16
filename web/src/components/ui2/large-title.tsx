import { cx } from './cx'
import { NavAccessory } from './nav-accessory'

/** The nument logotype (lowercase, bold, tight), as text so it stays crisp at any size. */
export function Wordmark({ className }: { className?: string }) {
  return <span className={cx('type-wordmark text-label-1', className)}>nument</span>
}

/**
 * The page header (mockups). Laptops: the date or a quiet line, the page title, one sentence, and the page's
 * actions at the trailing end. Phones: a top bar with the logotype (or a back link) and the search and account
 * buttons; the page title scrolls away under it and a small title fades in (pure CSS).
 */
export function LargeTitle({
  title,
  eyebrow,
  subtitle,
  actions,
  leading,
  compactTitle,
}: {
  title: string
  /** A shorter title for phones, when the laptop one is a sentence. */
  compactTitle?: string
  /** Quiet line above the title, such as today's date. */
  eyebrow?: React.ReactNode
  subtitle?: React.ReactNode
  /** Buttons at the trailing end of the header. */
  actions?: React.ReactNode
  /** A back link at the leading end of the phone top bar (and above the title on laptops). */
  leading?: React.ReactNode
}) {
  return (
    <>
      <div className="navbar-material sticky top-0 z-20 pt-[env(safe-area-inset-top)] lg:hidden">
        <div className="relative flex h-[var(--ui-navbar-h)] items-center gap-2 px-4">
          <div className="flex min-w-0 flex-1 items-center">{leading ?? <Wordmark className="text-[21px]" />}</div>
          <div aria-hidden className="navbar-title pointer-events-none absolute left-1/2 max-w-[44%] -translate-x-1/2 truncate text-[15px] font-semibold">
            {compactTitle ?? title}
          </div>
          <div className="flex flex-1 items-center justify-end gap-1">
            <NavAccessory />
          </div>
        </div>
      </div>
      <header className="mx-auto flex max-w-[1192px] flex-col gap-4 px-4 pt-2 pb-5 sm:px-6 lg:flex-row lg:items-end lg:justify-between lg:gap-6 lg:px-14 lg:pt-11 lg:pb-8">
        <div className="min-w-0">
          {leading ? <div className="mb-3 max-lg:hidden">{leading}</div> : null}
          {eyebrow ? <p className="text-[14px] text-label-3">{eyebrow}</p> : null}
          <h1 className="type-large-title mt-1.5 text-balance text-label-1">
            {compactTitle ? (
              <>
                <span className="lg:hidden">{compactTitle}</span>
                <span className="max-lg:hidden">{title}</span>
              </>
            ) : (
              title
            )}
          </h1>
          {subtitle ? <p className="mt-2 text-[15px] text-label-3">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </header>
    </>
  )
}

/** A v2 page: the header, then the content in the page column. */
export function Page({
  children,
  className,
  ...header
}: React.ComponentProps<typeof LargeTitle> & { children: React.ReactNode; className?: string }) {
  return (
    <>
      <LargeTitle {...header} />
      <div className={cx('mx-auto max-w-[1192px] px-4 sm:px-6 lg:px-14', className)}>{children}</div>
    </>
  )
}
