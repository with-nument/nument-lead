import type { Stage } from '@/lib/stages'
import { cx } from './cx'

/** v2 names for the stored stages: plain words a caller uses ('talking' reads as Replied). */
export const STAGE_V2: Record<Stage, { label: string; dot: string }> = {
  new: { label: 'New', dot: 'bg-stage-new' },
  contacted: { label: 'Contacted', dot: 'bg-stage-contacted' },
  talking: { label: 'Replied', dot: 'bg-stage-replied' },
  discovery_booked: { label: 'Call booked', dot: 'bg-stage-call-booked' },
  discovery_done: { label: 'Call done', dot: 'bg-stage-call-done' },
  proposal_sent: { label: 'Proposal', dot: 'bg-stage-proposal' },
  won: { label: 'Won', dot: 'bg-stage-won' },
  retainer: { label: 'Retainer', dot: 'bg-stage-retainer' },
  lost: { label: 'Lost', dot: 'bg-stage-lost' },
  not_now: { label: 'Not now', dot: 'bg-stage-not-now' },
  not_a_fit: { label: 'Not a fit', dot: 'bg-stage-not-a-fit' },
  wrong_contact: { label: 'Wrong contact', dot: 'bg-stage-wrong-contact' },
}

const stageInfo = (stage: string | null | undefined) => STAGE_V2[stage as Stage] ?? STAGE_V2.new

/** The v2 label for a stored stage value. */
export const stageLabel = (stage: string | null | undefined) => stageInfo(stage).label

/** A stage as a coloured dot and its name. The words carry the meaning; the dot helps scanning. */
export function StageLabel({ stage, className }: { stage: string | null | undefined; className?: string }) {
  const s = stageInfo(stage)
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap', className)}>
      <span aria-hidden className={cx('size-2 shrink-0 rounded-full', s.dot)} />
      {s.label}
    </span>
  )
}
