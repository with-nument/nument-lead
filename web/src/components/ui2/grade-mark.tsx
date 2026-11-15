import { gradeOf, type Grade } from '@/lib/grades'
import { cx } from './cx'

const TONE: Record<Grade, string> = {
  A: 'bg-grade-a text-grade-a-ink',
  B: 'bg-grade-b text-grade-b-ink',
  C: 'bg-grade-c text-grade-c-ink',
  D: 'bg-grade-d text-grade-d-ink hairline-ring',
}

const HINT: Record<Grade, string> = {
  A: 'Grade A: best fit, contact first',
  B: 'Grade B: good fit',
  C: 'Grade C: weaker fit',
  D: 'Grade D: poor fit',
}

/** A lead's grade as a small filled mark (a.circle.fill). D, the weakest, is an outline. */
export function GradeMark({ grade, size = 'regular', className }: { grade: string | null | undefined; size?: 'regular' | 'large'; className?: string }) {
  const g = gradeOf(grade)
  return (
    <span
      role="img"
      aria-label={`Grade ${g}`}
      title={HINT[g]}
      className={cx(
        'inline-grid shrink-0 place-items-center rounded-full leading-none font-bold',
        size === 'large' ? 'size-7 text-[15px]' : 'size-5 text-[11px]',
        TONE[g],
        className,
      )}
    >
      {g}
    </span>
  )
}
