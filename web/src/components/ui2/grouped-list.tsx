import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
import { cx } from './cx'

/**
 * A list of rows on a white surface: an optional header above, an optional footnote below.
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
      {header ? <h2 className="px-1 pb-2.5 text-[14px] text-label-3">{header}</h2> : null}
      <ul role="list" className="material-panel overflow-hidden rounded-panel">
        {children}
      </ul>
      {footer ? <p className="type-caption px-1 pt-2.5 text-label-3">{footer}</p> : null}
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

/** One row of a GroupedList: at least 56 px tall. */
export function ListRow({ href, onClick, chevron, current, tone = 'default', className, prefetch, ...body }: ListRowProps) {
  const showChevron = chevron ?? Boolean(href)
  const content = (
    <>
      {body.icon ? (
        <span aria-hidden className={cx('grid size-7 shrink-0 place-items-center [&_svg]:size-5', tone === 'default' ? 'text-label-2 [&_svg]:stroke-[1.6]' : null)}>
          {body.icon}
        </span>
      ) : null}
      <span className="flex min-w-0 flex-1 flex-col py-2.5 text-[15px]">
        <span className={cx('truncate', tone === 'accent' && 'font-[550] text-label-1', tone === 'destructive' && 'text-status-bad')}>{body.title}</span>
        {body.subtitle ? <span className="type-subhead truncate text-label-3">{body.subtitle}</span> : null}
      </span>
      {body.detail ? <span className="shrink-0 text-label-3">{body.detail}</span> : null}
      {body.accessory ? <span className="flex shrink-0 items-center">{body.accessory}</span> : null}
      {showChevron ? <ChevronRight aria-hidden className="-mr-1 size-4 shrink-0 text-label-2" strokeWidth={1.6} /> : null}
    </>
  )
  const row = cx('flex min-h-14 w-full items-center gap-4 px-4 py-1 text-left lg:px-[22px]', className)
  return (
    <li
      className={cx(
        'relative',
        // A full-width hairline between rows, hidden after the last one.
        'after:pointer-events-none after:absolute after:inset-x-0 after:bottom-0 after:h-px after:bg-separator last:after:hidden',
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
