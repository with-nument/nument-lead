import { Bot, CircleHelp, ConciergeBell, UserRound, type LucideIcon } from 'lucide-react'
import { cx } from './cx'

/** Who picks up a published number (contacts.line, migration 0018). */
export const LINE_V2: Record<string, { label: string; icon: LucideIcon; tone: string }> = {
  owner: { label: 'Owner direct', icon: UserRound, tone: 'text-line-owner' },
  front_desk: { label: 'Front desk', icon: ConciergeBell, tone: 'text-line-front-desk' },
  bot: { label: 'Bot or call centre', icon: Bot, tone: 'text-line-bot' },
  other: { label: 'Not sure who answers', icon: CircleHelp, tone: 'text-line-other' },
}

/** Owner direct, front desk, or a bot: what to expect when this number is called. */
export function WhoAnswers({ line, why, className }: { line: string | null | undefined; why?: string | null; className?: string }) {
  const l = LINE_V2[line ?? 'other'] ?? LINE_V2.other!
  const Icon = l.icon
  return (
    <span className={cx('inline-flex min-w-0 items-baseline gap-1.5', className)}>
      <Icon aria-hidden className={cx('size-[1.05em] shrink-0 translate-y-[0.15em]', l.tone)} strokeWidth={2.25} />
      <span className={cx('font-medium', l.tone)}>{l.label}</span>
      {why ? <span className="min-w-0 text-label-3">{why}</span> : null}
    </span>
  )
}
