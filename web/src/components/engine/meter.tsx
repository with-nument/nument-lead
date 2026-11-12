import { formatInr } from '@/lib/format'

/** Spend against the cap. The fill carries severity; the track is a lighter step of the same ramp. */
export function SpendMeter({ spend, cap, alertPct }: { spend: number; cap: number; alertPct: number }) {
  const ratio = cap > 0 ? spend / cap : 0
  const pct = Math.min(100, ratio * 100)
  const level = ratio >= 1 ? 'over' : ratio * 100 >= alertPct ? 'alert' : 'ok'
  const fill = level === 'over' ? 'var(--red-600)' : level === 'alert' ? 'var(--yellow-600)' : 'var(--indigo-600)'
  const track = level === 'over' ? 'var(--red-50)' : level === 'alert' ? 'var(--yellow-100)' : 'var(--indigo-100)'
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-display text-kpi text-tx-1">{formatInr(spend)}</span>
        <span className="text-sm text-tx-3">of {formatInr(cap)} today</span>
      </div>
      <div
        className="mt-2 h-2 rounded-full"
        style={{ background: track }}
        role="meter"
        aria-label="Spend today against the daily cap"
        aria-valuemin={0}
        aria-valuemax={cap}
        aria-valuenow={Math.round(spend)}
        aria-valuetext={`${formatInr(spend)} of ${formatInr(cap)}`}
      >
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: fill, minWidth: spend > 0 ? 4 : 0 }} />
      </div>
      <p className="mt-2 text-sm text-tx-3">
        {level === 'over' ? 'Over the daily cap.' : level === 'alert' ? `Past the ${alertPct}% alert line.` : `${Math.round(ratio * 100)}% used. Alert at ${alertPct}%.`}
      </p>
    </div>
  )
}
