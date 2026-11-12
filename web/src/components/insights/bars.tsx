import { formatNumber, formatPercent } from '@/lib/format'

/**
 * Horizontal bars in plain HTML (one series, one hue): thin bars with a 4px rounded data end,
 * square at the baseline, the value at the tip in text colours (dataviz mark specs).
 */
export function BarList({
  rows,
  max,
  label,
}: {
  rows: { key: string; label: string; value: number; note?: string }[]
  max?: number
  label: string
}) {
  const top = Math.max(1, max ?? Math.max(0, ...rows.map((r) => r.value)))
  return (
    <ul className="flex flex-col gap-3" aria-label={label}>
      {rows.map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(84px,140px)_minmax(0,1fr)] items-center gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
          <span className="truncate text-base text-tx-2">{r.label}</span>
          <div className="flex min-w-0 items-center gap-2" title={`${r.label}: ${formatNumber(r.value)}${r.note ? `, ${r.note}` : ''}`}>
            <div className="h-5 min-w-0 flex-1">
              <div className="h-full rounded-r-[4px] bg-indigo-600" style={{ width: `${(r.value / top) * 100}%`, minWidth: r.value > 0 ? 3 : 0 }} />
            </div>
            <span className="w-24 shrink-0 text-right text-sm text-tx-2 tabular">
              <span className="text-tx-1">{formatNumber(r.value)}</span>
              {r.note ? <span className="text-tx-3"> · {r.note}</span> : null}
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}

export const rate = (part: number, whole: number) => (whole > 0 ? formatPercent(part / whole) : '')
