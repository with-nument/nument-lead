'use client'

import { useId, useMemo, useState, useTransition } from 'react'
import { Check, CircleAlert, Copy } from 'lucide-react'
import { markFollowupSent } from '@/app/(app)/actions'
import { requestRegeneration, saveMessage, switchToAlternate } from '@/app/(app)/leads/[id]/actions'
import { cx } from '@/components/ui2/cx'
import { toast } from '@/components/ui2/toast'
import { formatDate, formatDateTime } from '@/lib/dates'
import { countWords, lintMessage, type MessageKind } from '@/lib/lint'
import { eyebrow, outlineClass, panel, plainClass, Status } from '../../_ui/marks'
import { useRun } from '../../_ui/use-run'
import { ContactButtons, type Channel } from './contact-buttons'
import type { LeadView } from './model'
import type { ConversationMessage, ConversationProps } from './types'

const textareaClass =
  'w-full resize-y rounded-control bg-fill-3 px-4 py-3 text-[17px] leading-[1.5] text-label-1 outline-none hairline-ring focus-visible:bg-panel lg:text-[15px]'

function Lint({ text, kind, id }: { text: string; kind: MessageKind; id: string }) {
  const problems = useMemo(() => (text.trim() ? lintMessage(text.trim(), kind) : []), [text, kind])
  if (!text.trim()) return <p id={id} className="type-subhead text-label-3">Empty</p>
  return problems.length ? (
    <ul id={id} aria-live="polite" className="type-subhead flex flex-col gap-1 text-status-bad">
      {problems.map((p) => (
        <li key={p} className="flex items-start gap-1.5">
          <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {p}
        </li>
      ))}
    </ul>
  ) : (
    <p id={id} aria-live="polite" className="type-subhead flex items-center gap-1.5 text-label-3">
      <Check aria-hidden className="size-3.5" />
      Reads well · {countWords(text)} words
    </p>
  )
}

/** One editable message with the house rules checked as you type. */
function Editor({
  leadId,
  kind,
  label,
  initial,
  canEdit,
  children,
}: {
  leadId: string
  kind: MessageKind
  label: React.ReactNode
  initial: string
  canEdit: boolean
  children?: (text: string, dirty: boolean) => React.ReactNode
}) {
  const id = useId()
  const [text, setText] = useState(initial)
  const [pending, start] = useTransition()
  const dirty = text.trim() !== initial.trim()
  const problems = text.trim() ? lintMessage(text.trim(), kind) : []
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className={eyebrow}>
        {label}
      </label>
      <textarea
        id={id}
        value={text}
        readOnly={!canEdit}
        onChange={(e) => setText(e.currentTarget.value)}
        rows={kind === 'message' ? 5 : 3}
        aria-describedby={`${id}-lint`}
        aria-invalid={problems.length > 0 || undefined}
        className={textareaClass}
      />
      <Lint text={text} kind={kind} id={`${id}-lint`} />
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {canEdit && dirty ? (
          <button
            type="button"
            className={outlineClass('small')}
            disabled={problems.length > 0 || pending}
            title={problems.length ? 'Fix the problems above to save' : undefined}
            onClick={() =>
              start(async () => {
                const r = await saveMessage({ leadId, field: kind, text })
                if (r.ok) toast(r.message ?? 'Saved')
                else toast.error(r.message)
              })
            }
          >
            Save
          </button>
        ) : null}
        {text ? (
          <button
            type="button"
            className={plainClass('small')}
            onClick={() => {
              void navigator.clipboard?.writeText(text).then(() => toast('Copied'))
            }}
          >
            <Copy aria-hidden />
            Copy
          </button>
        ) : null}
        {children?.(text, dirty)}
      </div>
    </div>
  )
}

/** The lead's own message and follow-ups, when there is no email thread (yet). */
function Messages({ view, canEdit, onOpen }: { view: LeadView; canEdit: boolean; onOpen: (channel: Channel) => void }) {
  const { pending, run } = useRun()
  const [, startFollowup] = useTransition()
  const sendFollowup = (which: 'd3' | 'd7', channel: Channel) =>
    startFollowup(async () => {
      const r = await markFollowupSent({ leadId: view.id, which, channel })
      if (r.ok) toast(r.message ?? 'Saved')
      else toast.error(r.message)
    })
  const followup = (which: 'd3' | 'd7', text: string, sentOn: string | null, label: string) => (
    <div key={`${which}-${text}`} className="px-5 py-5 hairline-t lg:px-[26px]">
      <Editor leadId={view.id} kind={which === 'd3' ? 'followup_d3' : 'followup_d7'} label={label} initial={text} canEdit={canEdit}>
        {(current, dirty) =>
          sentOn ? (
            <span className="type-subhead ml-auto text-label-3">Sent {sentOn}</span>
          ) : canEdit && current && view.firstMessage ? (
            <ContactButtons className="ml-auto" target={{ ...view.target, message: current }} disabled={dirty} onOpen={(ch) => sendFollowup(which, ch)} />
          ) : null
        }
      </Editor>
    </div>
  )
  return (
    <section aria-label="Messages" className={panel}>
      <div key={`${view.message}|${view.messageAlt}`} className="px-5 py-5 lg:px-[26px] lg:py-[22px]">
        {view.needsEdit || view.regenRequested ? (
          <p className="type-subhead mb-3 flex flex-wrap gap-x-4 text-label-2">
            {view.needsEdit ? <Status tone="warn">Needs your edit</Status> : null}
            {view.regenRequested ? <Status tone="muted">New message requested</Status> : null}
          </p>
        ) : null}
        <Editor leadId={view.id} kind="message" label={view.firstMessage ? `First message · sent ${view.firstMessage}` : 'First message'} initial={view.message} canEdit={canEdit}>
          {(text, dirty) =>
            canEdit ? (
              <>
                {view.messageAlt ? (
                  <button type="button" className={plainClass('small')} disabled={pending} onClick={() => run(() => switchToAlternate(view.id))}>
                    Use the alternate
                  </button>
                ) : null}
                <button type="button" className={plainClass('small')} disabled={pending || view.regenRequested} onClick={() => run(() => requestRegeneration(view.id))}>
                  Write a new one
                </button>
                <ContactButtons
                  className="lg:ml-auto"
                  target={{ ...view.target, message: text, emailSubject: view.emailSubject, emailBody: view.emailBody ?? text }}
                  disabled={dirty}
                  onOpen={onOpen}
                />
              </>
            ) : null
          }
        </Editor>
        {view.messageAlt ? (
          <details className="mt-5 rounded-control px-4 py-3 hairline-ring">
            <summary className="type-subhead cursor-pointer font-medium text-label-2">Alternate message</summary>
            <div className="mt-3">
              <Editor leadId={view.id} kind="message_alt" label="Alternate" initial={view.messageAlt} canEdit={canEdit} />
            </div>
          </details>
        ) : null}
      </div>
      {followup('d3', view.followups.d3, view.followups.d3SentOn, 'Day 3 follow-up, only if there is no reply')}
      {followup('d7', view.followups.d7, view.followups.d7SentOn, 'Day 7 follow-up, only if there is no reply')}
    </section>
  )
}

const STEP_LABEL: Record<number, string> = { 0: 'Day 1', 3: 'Day 3', 7: 'Day 7', 12: 'Day 12' }

function Bubble({ m, now }: { m: ConversationMessage; now: Date }) {
  const mine = m.direction === 'out'
  const when = m.at ? (m.status === 'queued' ? `Goes ${formatDateTime(m.at)}` : formatDate(m.at, now)) : ''
  const label = mine ? [m.step !== null ? (STEP_LABEL[m.step] ?? `Day ${m.step}`) : 'Reply', m.status === 'sent' ? null : m.status].filter(Boolean).join(' · ') : (m.from ?? 'They wrote')
  return (
    <li className={cx('flex flex-col', mine ? 'items-end' : 'items-start')}>
      <div className={cx('max-w-[92%] rounded-panel px-4 py-3 lg:max-w-[80%]', mine ? 'bg-fill-3 hairline-ring' : 'bg-panel hairline-ring')}>
        {m.subject && m.step === 0 ? <p className="type-subhead mb-1 font-semibold text-label-2">{m.subject}</p> : null}
        <p className="whitespace-pre-line text-label-1">{m.body ?? ''}</p>
      </div>
      <p className="type-caption mt-1 px-1 text-label-3">{[label, when].filter(Boolean).join(' · ')}</p>
    </li>
  )
}

/**
 * Conversation: the email thread when there is one (lane W3 supplies it), with the suggested reply to
 * approve; otherwise the lead's own first message and follow-ups.
 */
export function Conversation({
  view,
  thread,
  canEdit,
  onOpen,
  reply,
  onReply,
}: Omit<ConversationProps, 'leadId' | 'approveReply'> & {
  view: LeadView
  canEdit: boolean
  onOpen: (channel: Channel) => void
  reply: string
  onReply: (text: string) => void
}) {
  const now = useMemo(() => new Date(view.now), [view.now])
  if (!thread) return <Messages view={view} canEdit={canEdit} onOpen={onOpen} />
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Email thread" className={cx(panel, 'px-4 py-5 lg:px-[26px]')}>
        <p className="type-subhead mb-4 text-label-3">
          With {thread.toEmail}
          {thread.status !== 'open' ? ` · ${thread.status === 'stopped' ? `stopped${thread.stopReason ? `: ${thread.stopReason}` : ''}` : 'finished'}` : ''}
          {thread.pausedUntil ? ` · paused until ${formatDate(thread.pausedUntil, now)}` : ''}
        </p>
        {thread.messages.length ? (
          <ol className="flex flex-col gap-4">
            {thread.messages.map((m) => (
              <Bubble key={m.id} m={m} now={now} />
            ))}
          </ol>
        ) : (
          <p className="type-body text-label-3">No emails yet.</p>
        )}
      </section>
      {thread.suggestedReply ? (
        <section aria-labelledby="reply-h" className={cx(panel, 'px-5 py-5 lg:px-[26px]')}>
          <label id="reply-h" htmlFor="suggested-reply" className={cx(eyebrow, 'mb-2 block')}>
            Suggested reply
          </label>
          <textarea
            id="suggested-reply"
            rows={6}
            value={reply}
            readOnly={!canEdit}
            onChange={(e) => onReply(e.currentTarget.value)}
            className={textareaClass}
          />
          <p className="type-subhead mt-2 text-label-3">Edit it here, then approve it at the top. Nothing is sent until you approve.</p>
        </section>
      ) : null}
    </div>
  )
}
