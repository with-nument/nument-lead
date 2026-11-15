import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
import { cx } from './cx'

/**
 * An inset grouped list (iOS Settings, macOS System Settings): an optional header above, a
 * translucent panel of rows, an optional footnote below.
 */
export function GroupedList({
  header,
  footer,
  children,
  className,
  label,
}: {
  header?: React.ReactNode
  footer?: React.ReactNode
  children: React.ReactNode
  className?: string
  /** Accessible name when there is no visible header. */
  label?: string
}) {
  return (
    <section className={cx('flex flex-col', className)} aria-label={label}>
      {header ? <h2 className="type-subhead px-4 pb-2 font-semibold text-label-2">{header}</h2> : null}
      <ul role="list" className="material-panel overflow-hidden rounded-panel">
        {children}
      </ul>
      {footer ? <p className="type-caption px-4 pt-2 text-label-3">{footer}</p> : null}
    </section>
  )
}

type RowBody = {
  /** A small icon before the title. Rows with icons inset their separator to the text. */
  icon?: React.ReactNode
  title: React.ReactNode
  subtitle?: React.ReactNode
  /** Quiet trailing text, such as a count or a date. */
  detail?: React.ReactNode
  /** Trailing control (a switch, a button, a stage label...). */
  accessory?: React.ReactNode
}

type ListRowProps = RowBody & {
  href?: string
  onClick?: () => void
  /** Shows the disclosure chevron. On by default for links. */
  chevron?: boolean
  current?: boolean
  tone?: 'default' | 'accent' | 'destructive'
  className?: string
  prefetch?: boolean
}

const interactive =
  'transition-colors duration-[var(--ui-dur-1)] hover:bg-fill-3 active:bg-fill-2 aria-[current=page]:bg-fill-2 focus-visible:-outline-offset-2'

/** One row of a GroupedList: at least 44 px tall on phones, 40 px on laptops. */
export function ListRow({ href, onClick, chevron, current, tone = 'default', className, prefetch, ...body }: ListRowProps) {
  const showChevron = chevron ?? Boolean(href)
  const content = (
    <>
      {body.icon ? (
        <span aria-hidden className={cx('grid size-7 shrink-0 place-items-center [&_svg]:size-5', tone === 'default' ? 'text-accent' : null)}>
          {body.icon}
        </span>
      ) : null}
      <span className="flex min-w-0 flex-1 flex-col py-2.5">
        <span className={cx('truncate', tone === 'accent' && 'text-accent', tone === 'destructive' && 'text-status-bad')}>{body.title}</span>
        {body.subtitle ? <span className="type-subhead truncate text-label-3">{body.subtitle}</span> : null}
      </span>
      {body.detail ? <span className="shrink-0 text-label-3">{body.detail}</span> : null}
      {body.accessory ? <span className="flex shrink-0 items-center">{body.accessory}</span> : null}
      {showChevron ? <ChevronRight aria-hidden className="-mr-1 size-[18px] shrink-0 text-label-3 lg:size-4" strokeWidth={2.25} /> : null}
    </>
  )
  const row = cx('flex min-h-11 w-full items-center gap-3 px-4 text-left lg:min-h-10', className)
  return (
    <li
      className={cx(
        'relative',
        // Separator, inset to the text like iOS. Hidden after the last row.
        'after:pointer-events-none after:absolute after:right-0 after:bottom-0 after:h-[var(--ui-hairline)] after:bg-separator last:after:hidden',
        body.icon ? 'after:left-14' : 'after:left-4',
      )}
    >
      {href ? (
        <Link href={href} prefetch={prefetch} aria-current={current ? 'page' : undefined} className={cx(row, interactive)}>
          {content}
        </Link>
      ) : onClick ? (
        <button type="button" onClick={onClick} className={cx(row, interactive)}>
          {content}
        </button>
      ) : (
        <div className={row}>{content}</div>
      )}
    </li>
  )
}
