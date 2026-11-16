import { gradeOf } from '@/lib/grades'
import { cx } from '@/components/ui2/cx'

/** A content surface: white panel, hairline edge, large radius. */
export const panel = 'material-panel rounded-panel'

/** Small quiet heading inside a panel ("Founder", "Next step"). */
export const eyebrow = 'type-subhead font-medium text-label-3'

const GRADE_TONE = {
  A: 'text-label-1 shadow-[inset_0_0_0_1.5px_var(--ui-label-1)]',
  B: 'text-label-2 hairline-ring',
  C: 'text-label-3 hairline-ring',
  D: 'text-label-3 hairline-ring',
} as const

/** A grade as an outlined letter. A has the strongest edge; C and D are the quietest. */
export function GradeLetter({ grade, className }: { grade: string | null | undefined; className?: string }) {
  const g = gradeOf(grade)
  return (
    <span
      role="img"
      aria-label={`Grade ${g}`}
      className={cx('inline-grid size-6 shrink-0 place-items-center rounded-[7px] text-[12.5px] leading-none font-semibold', GRADE_TONE[g], className)}
    >
      {g}
    </span>
  )
}

export type DotTone = 'ok' | 'warn' | 'bad' | 'ink' | 'muted' | 'none'

const DOT: Record<DotTone, string> = {
  ok: 'bg-status-ok',
  warn: 'bg-status-warn',
  bad: 'bg-status-bad',
  ink: 'bg-label-2',
  muted: 'bg-label-3',
  none: 'shadow-[inset_0_0_0_1.5px_var(--ui-separator-strong)]',
}

/** A tiny status dot. The words beside it carry the meaning. */
export function Dot({ tone, className }: { tone: DotTone; className?: string }) {
  return <span aria-hidden className={cx('inline-block size-[7px] shrink-0 rounded-full', DOT[tone], className)} />
}

/** A dot and its words, on one line. */
export function Status({ tone, children, className }: { tone: DotTone; children: React.ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-[7px] whitespace-nowrap', className)}>
      <Dot tone={tone} />
      {children}
    </span>
  )
}

/** The company's first letter on a soft grey rounded square with a hairline edge (no logos are fetched). */
export function Monogram({ name, size = 'large' }: { name: string; size?: 'large' | 'small' }) {
  const letter = name.trim().charAt(0).toUpperCase() || '?'
  return (
    <span
      aria-hidden
      className={cx(
        'grid shrink-0 place-items-center font-semibold',
        'bg-fill-2 text-label-2 hairline-ring',
        size === 'large' ? 'size-11 rounded-[12px] text-[18px]' : 'size-8 rounded-[9px] text-[14px]',
      )}
    >
      {letter}
    </span>
  )
}

const BTN =
  'relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-control font-medium ' +
  'transition-colors duration-[var(--ui-dur-1)] disabled:pointer-events-none disabled:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40 ' +
  '[&_svg]:size-[1.1em] [&_svg]:shrink-0'
const BTN_SIZE = {
  small: 'h-9 px-3 text-[15px] lg:h-8 lg:px-3 lg:text-[13px]',
  regular: 'h-11 px-4 text-[17px] lg:h-[38px] lg:px-[15px] lg:text-[14px]',
} as const

/** An outlined button (white, hairline edge): every button on a page except the one solid one. */
export function outlineClass(size: keyof typeof BTN_SIZE = 'regular', extra?: string) {
  return cx(BTN, BTN_SIZE[size], 'bg-panel text-label-1 hairline-ring hover:bg-fill-3 active:bg-fill-2', extra)
}

/** A plain text button: no edge until hovered. */
export function plainClass(size: keyof typeof BTN_SIZE = 'regular', extra?: string) {
  return cx(BTN, BTN_SIZE[size], 'text-label-2 hover:bg-fill-3 hover:text-label-1 active:bg-fill-2', extra)
}
