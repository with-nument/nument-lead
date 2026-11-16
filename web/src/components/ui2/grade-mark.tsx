import { gradeOf, type Grade } from '@/lib/grades'
import { cx } from './cx'

// Outlined letters (mockups): A has the darkest ring, D the faintest. The fill stays clear.
const TONE: Record<Grade, string> = {
  A: 'text-grade-a-ink border-grade-a-ring border-[1.5px]',
  B: 'text-grade-b-ink border-grade-b-ring border',
  C: 'text-grade-c-ink border-grade-c-ring border',
  D: 'text-grade-d-ink border-grade-d-ring border border-dashed',
}

const HINT: Record<Grade, string> = {
  A: 'Grade A: best fit, contact first',
  B: 'Grade B: good fit',
  C: 'Grade C: weaker fit',
  D: 'Grade D: poor fit',
}

/** A lead's grade as a small outlined letter. */
export function GradeMark({ grade, size = 'regular', className }: { grade: string | null | undefined; size?: 'regular' | 'large'; className?: string }) {
  const g = gradeOf(grade)
  return (
    <span
      role="img"
      aria-label={`Grade ${g}`}
      title={HINT[g]}
      className={cx(
        'inline-grid shrink-0 place-items-center leading-none font-semibold',
        size === 'large' ? 'size-8 rounded-[9px] text-[14px]' : 'size-6 rounded-[7px] text-[12.5px]',
        TONE[g],
        className,
      )}
    >
      {g}
    </span>
  )
}
