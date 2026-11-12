import { cn } from '@/lib/cn'

export function KpiTile({
  label,
  value,
  hint,
  tone = 'default',
  className,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  tone?: 'default' | 'money' | 'alert'
  className?: string
}) {
  const color = tone === 'money' ? 'var(--green-800)' : tone === 'alert' ? 'var(--red-600)' : 'var(--indigo-900)'
  return (
    <div className={cn('rounded-xl border border-line-2 bg-surface px-4 py-3', className)}>
      <div className="label-mono truncate">{label}</div>
      <div className="mt-1.5 font-display text-kpi tabular" style={{ color }}>
        {value}
      </div>
      {hint ? <div className="mt-1 truncate text-xs text-tx-3">{hint}</div> : null}
    </div>
  )
}
