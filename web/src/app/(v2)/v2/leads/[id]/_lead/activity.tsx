'use client'

import { useId, useRef, useState, useTransition } from 'react'
import { FileText, ThumbsDown, ThumbsUp, Upload } from 'lucide-react'
import { addNote, proposalLink, sendFeedback, setLostReason, updateNextStep, uploadProposal } from '@/app/(app)/leads/[id]/actions'
import { cx } from '@/components/ui2/cx'
import { Select } from '@/components/ui2/select'
import { STAGE_V2 } from '@/components/ui2/stage-label'
import { toast } from '@/components/ui2/toast'
import { FEEDBACK_REASONS, type FeedbackReason } from '@/lib/feedback'
import { formatInr } from '@/lib/format'
import { formatMoney, LOST_REASONS, needsLostReason, type LostReason } from '@/lib/outcomes'
import { STAGE_VALUES, type Stage } from '@/lib/stages'
import { eyebrow, outlineClass, panel, plainClass } from '../../_ui/marks'
import { DealFields, fieldClass } from '../../_ui/stage-move'
import { useRun } from '../../_ui/use-run'
import type { LeadView } from './model'

const block = 'px-5 py-5 lg:px-[26px] [&+&]:hairline-t'

export type Proposal = { path: string; name: string; size: number }
export type MyFeedback = { rating: number; reason: string | null } | null

/** Stage, next step, notes, the deal (admins), lead quality, and every change on the lead. */
export function Activity({
  view,
  stage,
  canEdit,
  isAdmin,
  proposals,
  myFeedback,
  onStage,
}: {
  view: LeadView
  stage: string
  canEdit: boolean
  isAdmin: boolean
  proposals: Proposal[]
  myFeedback: MyFeedback
  onStage: (to: Stage) => void
}) {
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Where it stands" className={panel}>
        <div className={block}>
          <StageRow view={view} stage={stage} canEdit={canEdit} onStage={onStage} />
        </div>
        <div className={block}>
          {canEdit ? (
            <NextStep key={`${view.nextStep}-${view.dueAt}`} leadId={view.id} nextStep={view.nextStep} dueAt={view.dueAt} />
          ) : (
            <>
              <h3 className={eyebrow}>Next step</h3>
              <p className="mt-1 text-label-1">{view.nextStep ?? 'None set'}</p>
              {view.dueLabel ? <p className="type-subhead text-label-3">Due {view.dueLabel}</p> : null}
            </>
          )}
        </div>
        <div className={block}>
          <Notes key={view.notes ?? ''} leadId={view.id} latest={view.notes} canEdit={canEdit} />
        </div>
      </section>

      {isAdmin ? <Deal view={view} proposals={proposals} /> : null}

      <section aria-label="Lead quality" className={cx(panel, block)}>
        <Feedback leadId={view.id} mine={myFeedback} />
      </section>

      <section aria-labelledby="timeline-h" className={cx(panel, block)}>
        <h3 id="timeline-h" className={cx(eyebrow, 'mb-3')}>
          Everything that happened
        </h3>
        {view.activities.length ? (
          <ol className="relative flex flex-col gap-4 pl-[18px] before:absolute before:top-2 before:bottom-2 before:left-[3px] before:w-px before:bg-separator-strong">
            {view.activities.map((a) => (
              <li key={a.id} className="relative">
                <span aria-hidden className="absolute top-[7px] -left-[18px] size-[7px] rounded-full bg-panel shadow-[inset_0_0_0_1.5px_var(--ui-label-3)]" />
                <p className="text-label-1">{a.text}</p>
                {a.note ? <p className="type-subhead mt-1 rounded-control bg-fill-3 px-3 py-2 whitespace-pre-line text-label-2">{a.note}</p> : null}
                <p className="type-caption mt-0.5 text-label-3">
                  <time dateTime={a.at}>{a.when}</time> · {a.ago} · {a.source}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="type-body text-label-3">Nothing has happened on this lead yet.</p>
        )}
      </section>

      {view.pages.length ? (
        <section aria-labelledby="pages-h" className={cx(panel, block)}>
          <h3 id="pages-h" className={cx(eyebrow, 'mb-2')}>
            Pages the engine read
          </h3>
          <ul className="flex flex-col gap-2">
            {view.pages.map((p) => (
              <li key={p.id} className="min-w-0">
                <a href={p.url} target="_blank" rel="noopener noreferrer" className="block truncate text-label-1 hover:underline">
                  {p.title}
                </a>
                <p className="type-caption text-label-3">
                  {p.host} · read {p.read}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}

function StageRow({ view, stage, canEdit, onStage }: { view: LeadView; stage: string; canEdit: boolean; onStage: (to: Stage) => void }) {
  const id = useId()
  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex min-w-[200px] flex-col gap-1.5">
        <label htmlFor={id} className={eyebrow}>
          Stage
        </label>
        {canEdit ? (
          <Select id={id} value={stage} onChange={(e) => onStage(e.currentTarget.value as Stage)}>
            {STAGE_VALUES.map((s) => (
              <option key={s} value={s}>
                {STAGE_V2[s].label}
              </option>
            ))}
          </Select>
        ) : (
          <p id={id} className="text-label-1">
            {STAGE_V2[stage as Stage]?.label ?? stage}
          </p>
        )}
      </div>
      {needsLostReason(stage) && canEdit ? <Reason key={view.lostReason ?? ''} leadId={view.id} reason={view.lostReason} /> : null}
      <dl className="type-subhead ml-auto flex gap-6 text-label-3">
        {view.firstMessage ? (
          <div>
            <dt>First message</dt>
            <dd className="text-label-1">{view.firstMessage}</dd>
          </div>
        ) : null}
        {view.added ? (
          <div>
            <dt>Found</dt>
            <dd className="text-label-1">{view.added}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  )
}

/** Why a Lost or Not now lead closed, changeable in place. */
function Reason({ leadId, reason }: { leadId: string; reason: string | null }) {
  const id = useId()
  const { pending, run } = useRun()
  const [value, setValue] = useState(reason ?? '')
  return (
    <div className="flex min-w-[200px] flex-col gap-1.5">
      <label htmlFor={id} className={eyebrow}>
        Reason
      </label>
      <Select
        id={id}
        value={value}
        disabled={pending}
        onChange={(e) => {
          const next = e.currentTarget.value as LostReason | ''
          if (!next) return
          const prev = value
          setValue(next)
          run(async () => {
            const r = await setLostReason({ leadId, reason: next })
            if (!r.ok) setValue(prev)
            return r
          })
        }}
      >
        <option value="">Choose a reason…</option>
        {LOST_REASONS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </Select>
    </div>
  )
}

function NextStep({ leadId, nextStep, dueAt }: { leadId: string; nextStep: string | null; dueAt: string | null }) {
  const id = useId()
  const { pending, run } = useRun()
  const [step, setStep] = useState(nextStep ?? '')
  const [due, setDue] = useState(dueAt ?? '')
  const dirty = step !== (nextStep ?? '') || due !== (dueAt ?? '')
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        run(() => updateNextStep({ leadId, nextStep: step, dueAt: due }))
      }}
    >
      <label htmlFor={`${id}-step`} className="flex min-w-0 flex-1 basis-60 flex-col gap-1.5">
        <span className={eyebrow}>Next step</span>
        <input id={`${id}-step`} value={step} maxLength={120} onChange={(e) => setStep(e.currentTarget.value)} placeholder="Book the call" className={fieldClass} />
      </label>
      <label htmlFor={`${id}-due`} className="flex w-44 flex-col gap-1.5">
        <span className={eyebrow}>Due</span>
        <input id={`${id}-due`} type="date" value={due} onChange={(e) => setDue(e.currentTarget.value)} className={fieldClass} />
      </label>
      {dirty ? (
        <button type="submit" disabled={pending} className={outlineClass()}>
          Save
        </button>
      ) : null}
    </form>
  )
}

function Notes({ leadId, latest, canEdit }: { leadId: string; latest: string | null; canEdit: boolean }) {
  const id = useId()
  const { pending, run } = useRun()
  const [text, setText] = useState('')
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className={eyebrow}>
        Notes
      </label>
      {latest ? <p className="whitespace-pre-line text-label-1">{latest}</p> : <p className="text-label-3">No notes yet.</p>}
      {canEdit ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => addNote({ leadId, text }), () => setText(''))
          }}
        >
          <textarea
            id={id}
            rows={2}
            value={text}
            maxLength={1000}
            onChange={(e) => setText(e.currentTarget.value)}
            placeholder="What happened, what is next. The newest note is also the sheet's Notes."
            className="w-full resize-y rounded-control bg-fill-3 px-4 py-3 text-label-1 outline-none hairline-ring focus-visible:bg-panel"
          />
          {text.trim() ? (
            <div className="flex justify-end">
              <button type="submit" disabled={pending} className={outlineClass('small')}>
                Add note
              </button>
            </div>
          ) : null}
        </form>
      ) : null}
    </div>
  )
}

function Deal({ view, proposals }: { view: LeadView; proposals: Proposal[] }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, startUpload] = useTransition()
  const m = view.money
  const summary = [m?.deal != null ? formatInr(m.deal) : '', m?.retainer != null ? `${formatMoney(m.retainer, m.currency)} a month` : ''].filter(Boolean).join(' · ')
  return (
    <section aria-labelledby="deal-h" className={panel}>
      <div className={block}>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h3 id="deal-h" className={eyebrow}>
            Deal · only admins see this
          </h3>
          {summary ? <span className="type-subhead text-label-2">{summary}</span> : null}
        </div>
        <DealFields key={`${m?.deal}-${m?.retainer}-${m?.currency}`} leadId={view.id} money={m} />
      </div>
      <div className={block}>
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className={eyebrow}>Proposals</h3>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="sr-only"
            aria-label="Choose a proposal file"
            onChange={(e) => {
              const file = e.currentTarget.files?.[0]
              if (!file) return
              const fd = new FormData()
              fd.set('file', file)
              startUpload(async () => {
                const r = await uploadProposal(view.id, fd)
                if (r.ok) toast(r.message ?? 'Uploaded')
                else toast.error(r.message)
                if (fileRef.current) fileRef.current.value = ''
              })
            }}
          />
          <button type="button" disabled={uploading} onClick={() => fileRef.current?.click()} className={outlineClass('small')}>
            <Upload aria-hidden />
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
        {proposals.length ? (
          <ul className="flex flex-col">
            {proposals.map((p) => (
              <li key={p.path}>
                <button
                  type="button"
                  className="flex min-h-11 w-full items-center gap-2 rounded-control px-2 text-left text-label-1 hover:bg-fill-3 lg:min-h-9"
                  onClick={async () => {
                    const r = await proposalLink(p.path)
                    // The signed link answers with a download, so the page itself stays put.
                    if (r.ok && r.data) window.location.assign(r.data)
                    else toast.error(r.ok ? 'Could not open the file.' : r.message)
                  }}
                >
                  <FileText aria-hidden className="size-4 shrink-0 text-label-3" />
                  <span className="truncate">{p.name}</span>
                  {p.size ? <span className="type-caption ml-auto shrink-0 text-label-3">{Math.max(1, Math.round(p.size / 1024))} KB</span> : null}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="type-subhead text-label-3">PDF or Word, up to 10 MB. Stored privately.</p>
        )}
      </div>
    </section>
  )
}

function Feedback({ leadId, mine }: { leadId: string; mine: MyFeedback }) {
  const id = useId()
  const { pending, run } = useRun()
  const [rating, setRating] = useState<1 | -1 | null>(mine ? (mine.rating > 0 ? 1 : -1) : null)
  const [reason, setReason] = useState<FeedbackReason>((mine?.reason as FeedbackReason) ?? 'Great lead')
  return (
    <div className="flex flex-col gap-3">
      <h3 className={eyebrow}>Is this a good lead? Your vote trains the scoring.</h3>
      <div role="group" aria-label="Rate this lead" className="flex flex-wrap gap-2">
        {([1, -1] as const).map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={rating === r}
            onClick={() => {
              setRating(r)
              setReason(r === 1 ? 'Great lead' : 'No real need')
            }}
            className={cx(outlineClass('small'), rating === r && 'shadow-[inset_0_0_0_1.5px_var(--ui-label-1)]')}
          >
            {r === 1 ? <ThumbsUp aria-hidden /> : <ThumbsDown aria-hidden />}
            {r === 1 ? 'Good lead' : 'Not good'}
          </button>
        ))}
      </div>
      {rating !== null ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => sendFeedback({ leadId, rating, reason }))
          }}
        >
          <label htmlFor={id} className="sr-only">
            Reason
          </label>
          <Select id={id} value={reason} onChange={(e) => setReason(e.currentTarget.value as FeedbackReason)} className="min-w-[200px]">
            {FEEDBACK_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
          <button type="submit" disabled={pending} className={plainClass('small')}>
            Send
          </button>
        </form>
      ) : null}
    </div>
  )
}
