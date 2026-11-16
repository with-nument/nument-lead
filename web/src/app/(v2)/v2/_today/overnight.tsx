import Link from 'next/link'
import { cx } from '@/components/ui2/cx'
import type { OvernightHealth, OvernightStat } from './types'

export type OvernightCardProps = {
  title: string
  /** Quiet text at the right of the title, such as "1:00 – 4:12 am". */
  window?: string
  rows: OvernightStat[]
  health?: OvernightHealth | null
  link?: { href: string; label: string }
}

const DOT: Record<OvernightHealth['tone'], string> = { ok: 'bg-dot-ok', warn: 'bg-dot-warn', bad: 'bg-dot-bad' }

/** The numbers card beside the steps (mockup "Overnight"): label and number rows, a health line, one link. */
export function OvernightCard({ title, window, rows, health, link }: OvernightCardProps) {
  return (
    <aside aria-labelledby="overnight-title" className="material-panel rounded-panel px-[22px] pt-5 pb-[18px] lg:sticky lg:top-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="overnight-title" className="type-headline text-label-1">
          {title}
        </h2>
        {window ? <span className="text-[12px] text-label-3">{window}</span> : null}
      </div>
      <dl className="mt-2.5">
        {rows.map((r, i) => (
          <div key={r.label} className={cx('flex items-baseline justify-between py-[11px] text-[14.5px]', i > 0 && 'border-t border-separator')}>
            <dt className="text-label-3">{r.label}</dt>
            <dd className="text-[15px] font-[550] text-label-1 tabular-nums">{r.value}</dd>
          </div>
        ))}
      </dl>
      {health || link ? <div className="mt-1.5 mb-3.5 h-px bg-separator" /> : null}
      {health ? (
        <p className="flex items-center gap-[7px] text-[13.5px] text-label-2">
          <span aria-hidden className={cx('size-[7px] shrink-0 rounded-full', DOT[health.tone])} />
          {health.text}
        </p>
      ) : null}
      {link ? (
        <Link href={link.href} className="mt-4 inline-block text-[14px] text-label-1 underline decoration-separator-strong underline-offset-[3px]">
          {link.label}
        </Link>
      ) : null}
    </aside>
  )
}
