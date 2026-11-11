import { cn } from '@/lib/cn'
import { GRADE_STYLE, gradeOf } from '@/lib/grades'
import { stageOf } from '@/lib/stages'

const flat = 'inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-[6px] px-2 text-xs font-medium'

export function StageBadge({ stage, className }: { stage: string | null | undefined; className?: string }) {
  const s = stageOf(stage)
  return (
    <span className={cn(flat, className)} style={{ background: s.bg, color: s.fg }}>
      {s.label}
    </span>
  )
}

export function GradeBadge({ grade, className }: { grade: string | null | undefined; className?: string }) {
  const g = gradeOf(grade)
  const style = GRADE_STYLE[g]
  return (
    <span
      className={cn('inline-flex size-6 shrink-0 items-center justify-center rounded-[6px] text-xs font-semibold', className)}
      style={{ background: style.bg, color: style.fg }}
      title={`Grade ${g}`}
    >
      <span className="sr-only">Grade </span>
      {g}
    </span>
  )
}

export type Tone = 'neutral' | 'indigo' | 'ok' | 'warn' | 'bad'
const tones: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-tx-2',
  indigo: 'bg-indigo-100 text-indigo-900',
  ok: 'bg-green-100 text-green-800',
  warn: 'bg-yellow-100 text-warn-ink',
  bad: 'bg-red-50 text-red-600',
}

/** Small flat rectangle for status words. Colour is never the only signal: the word is always there. */
export function Tag({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: React.ReactNode }) {
  return <span className={cn(flat, tones[tone], className)}>{children}</span>
}
