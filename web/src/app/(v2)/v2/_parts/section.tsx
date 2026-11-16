import { cx } from '@/components/ui2/cx'

// The calm building blocks of the Settings, Engine and Insights pages (mockup 07_settings): a titled group
// with an optional action beside the title, a white panel with hairline rows, label and value in each row.

export function Section({
  id,
  title,
  description,
  action,
  children,
  className,
}: {
  id: string
  title: string
  description?: React.ReactNode
  /** One outlined button beside the title (Invite, Add...). */
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section aria-labelledby={id} className={cx('flex min-w-0 flex-col', className)}>
      <div className="mb-2.5 flex items-end gap-3 px-1">
        <div className="min-w-0 flex-1">
          <h2 id={id} className="type-headline text-label-1">
            {title}
          </h2>
          {description ? <p className="type-subhead mt-0.5 text-label-3 lg:text-[13.5px]">{description}</p> : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}

/** The white surface (material-panel): large radius, rows separated by hairlines. */
export function Panel({ children, className, label, divided = true }: { children: React.ReactNode; className?: string; label?: string; divided?: boolean }) {
  return (
    <div aria-label={label} role={label ? 'group' : undefined} className={cx('material-panel overflow-hidden rounded-[20px]', divided && '[&>*+*]:hairline-t', className)}>
      {children}
    </div>
  )
}

/** One row of a panel: a grey label column (optional), the value, then a trailing control. 56 px tall. */
export function Row({
  label,
  children,
  trailing,
  className,
  as: As = 'div',
}: {
  label?: React.ReactNode
  children?: React.ReactNode
  trailing?: React.ReactNode
  className?: string
  as?: 'div' | 'li'
}) {
  return (
    <As className={cx('flex min-h-14 items-center gap-3.5 px-4 py-3 text-[15px] lg:px-5 lg:text-[14.5px]', className)}>
      {label !== undefined ? <span className="w-[112px] shrink-0 text-label-3 sm:w-[130px]">{label}</span> : null}
      <div className="min-w-0 flex-1 text-label-1">{children}</div>
      {trailing !== undefined ? <div className="flex shrink-0 items-center gap-2">{trailing}</div> : null}
    </As>
  )
}

/** A tiny muted status dot (green, amber, red or grey) before a short word. */
export function StatusDot({ tone, children }: { tone: 'ok' | 'warn' | 'bad' | 'none'; children: React.ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <span
        aria-hidden
        className={cx(
          'size-1.5 shrink-0 rounded-full',
          tone === 'ok' && 'bg-status-ok',
          tone === 'warn' && 'bg-status-warn',
          tone === 'bad' && 'bg-status-bad',
          tone === 'none' && 'bg-label-3',
        )}
      />
      <span className="min-w-0">{children}</span>
    </span>
  )
}

/** A thin horizontal meter. `value` and `max` in the same unit; the share is clamped to 0..1. */
export function Meter({ value, max, label, tone = 'ink', className }: { value: number; max: number; label: string; tone?: 'ink' | 'grey' | 'bad'; className?: string }) {
  const share = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={Math.min(value, max)}
      className={cx('h-1.5 overflow-hidden rounded-full bg-fill-2', className)}
    >
      <span
        className={cx('block h-full rounded-full', tone === 'ink' && 'bg-label-2', tone === 'grey' && 'bg-label-3', tone === 'bad' && 'bg-status-bad')}
        style={{ width: `${share * 100}%` }}
      />
    </div>
  )
}

/** Two columns from 1024 px (the Settings mockup), one on phones. */
export function Columns({ children }: { children: React.ReactNode }) {
  return <div className="grid items-start gap-7 lg:grid-cols-2">{children}</div>
}

export function Column({ children }: { children: React.ReactNode }) {
  return <div className="flex min-w-0 flex-col gap-7">{children}</div>
}
