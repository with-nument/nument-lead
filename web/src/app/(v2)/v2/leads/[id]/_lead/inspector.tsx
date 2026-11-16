import { cx } from '@/components/ui2/cx'
import { formatDate, formatDateTime } from '@/lib/dates'
import { eyebrow, Status } from '../../_ui/marks'
import type { LeadView, MilestoneView } from './model'
import type { ConversationThread, PlanPageSummary } from './types'

const STEP_LABEL: Record<number, string> = { 0: 'Day 1', 3: 'Day 3', 7: 'Day 7', 12: 'Day 12' }

function threadMilestones(thread: ConversationThread, now: Date): MilestoneView[] {
  const day = (v: string | null) => (v ? formatDate(v, now) : '')
  return thread.messages.map((m) => {
    if (m.direction === 'in') return { label: `${m.from ?? 'They'} replied`, date: day(m.at), strong: true }
    const step = m.step !== null ? (STEP_LABEL[m.step] ?? `Day ${m.step}`) : 'Reply'
    const state = m.status === 'sent' ? 'sent' : m.status === 'queued' || m.status === 'approved' ? 'queued' : m.status === 'cancelled' ? 'paused' : m.status
    return { label: `${step} · ${state}`, date: m.status === 'sent' ? day(m.at) : '', faint: m.status !== 'sent' }
  })
}

/** The side panel: who to talk to, how they engaged, the messages so far, and the next step. */
export function Inspector({
  view,
  thread,
  planPage,
  now,
  flush,
}: {
  view: LeadView
  thread?: ConversationThread | null
  planPage?: PlanPageSummary | null
  now: Date
  /** No side padding (inside a sheet, which has its own). */
  flush?: boolean
}) {
  const person = view.people.find((p) => !p.blocked) ?? view.people[0]
  const milestones = thread ? threadMilestones(thread, now) : view.milestones
  const section = 'py-[18px] [&+&]:hairline-t'
  return (
    <div className={flush ? '' : 'px-5 py-1.5 lg:px-[22px]'}>
      {person ? (
        <section className={section} aria-label="Main contact">
          <h3 className={cx(eyebrow, 'mb-2.5')}>{person.isDecisionMaker ? 'Decision maker' : 'Contact'}</h3>
          <div className="flex items-center gap-3">
            <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-fill-2 text-[12.5px] font-semibold text-label-2 hairline-ring">
              {person.initials}
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold text-label-1">{person.name ?? 'Name not published'}</p>
              {person.role ? <p className="type-subhead truncate text-label-3">{person.role}</p> : null}
            </div>
          </div>
          {person.email ? <p className="mt-3 truncate text-[14px] text-label-1">{person.email}</p> : null}
          {person.phone && !person.email ? <p className="mt-3 text-[14px] text-label-1">{person.phoneDisplay}</p> : null}
          <p className="mt-1 text-[13px] text-label-2">
            {person.blocked ? (
              <Status tone="bad">Do not contact</Status>
            ) : person.verified ? (
              <Status tone="ok">Verified{person.verifiedOn ? ` on ${person.verifiedOn}` : ''}</Status>
            ) : (
              <Status tone="warn">Not verified yet</Status>
            )}
          </p>
        </section>
      ) : null}

      {planPage ? (
        <section className={section} aria-label="Plan page">
          <h3 className={cx(eyebrow, 'mb-2.5')}>Plan page</h3>
          <p className="flex items-baseline gap-2">
            <span className="text-[24px] font-semibold tracking-[-0.02em] text-label-1">{planPage.views}</span>
            <span className="type-subhead text-label-3">
              {planPage.views === 1 ? 'view' : 'views'}
              {planPage.lastViewedAt ? ` · last ${formatDateTime(planPage.lastViewedAt)}` : ''}
            </span>
          </p>
          {planPage.note ? <p className="type-subhead mt-0.5 text-label-3">{planPage.note}</p> : null}
        </section>
      ) : null}

      {milestones.length ? (
        <section className={section} aria-label={thread ? 'Emails' : 'Messages'}>
          <h3 className={cx(eyebrow, 'mb-2.5')}>{thread ? 'Emails' : 'Messages'}</h3>
          <ol className="relative pl-[18px] before:absolute before:top-2 before:bottom-2 before:left-[3px] before:w-px before:bg-separator-strong">
            {milestones.map((m, i) => (
              <li key={i} className={cx('relative flex justify-between gap-3 py-1 text-[14px]', m.faint ? 'text-label-3' : 'text-label-1')}>
                <span
                  aria-hidden
                  className={cx(
                    'absolute top-[11px] -left-[18px] size-[7px] rounded-full',
                    m.strong ? 'bg-panel shadow-[inset_0_0_0_2px_var(--ui-label-1)]' : 'bg-panel shadow-[inset_0_0_0_1.5px_var(--ui-label-3)]',
                  )}
                />
                <span className={cx(m.strong && 'font-semibold')}>{m.label}</span>
                <span className="shrink-0 text-label-3">{m.date}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className={section} aria-label="Next step">
        <h3 className={cx(eyebrow, 'mb-2')}>Next step</h3>
        <p className="text-[14.5px] text-label-1">{view.nextStep ?? 'None set. Add one under Activity.'}</p>
        {view.dueLabel ? (
          <p className="type-subhead mt-1 text-label-2">{view.overdue ? <Status tone="warn">Was due {view.dueLabel}</Status> : `Due ${view.dueLabel}`}</p>
        ) : null}
      </section>
    </div>
  )
}
