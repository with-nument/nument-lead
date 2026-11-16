import { cx } from './cx'

const SPOKES = Array.from({ length: 8 }, (_, i) => i)

/** An activity indicator: eight spokes stepping round, the newest one darkest. */
export function ActivityIndicator({ label = 'Loading', className }: { label?: string; className?: string }) {
  return (
    <span role="status" aria-label={label} className={cx('inline-block size-[1.15em] shrink-0', className)}>
      <svg viewBox="0 0 24 24" className="activity-spin size-full" aria-hidden>
        {SPOKES.map((i) => (
          <rect key={i} x="11" y="2.5" width="2" height="5.5" rx="1" fill="currentColor" opacity={0.18 + (i / 7) * 0.82} transform={`rotate(${i * 45} 12 12)`} />
        ))}
      </svg>
    </span>
  )
}
