'use client'

import { useRef, useState, useTransition } from 'react'
import { FileText, ThumbsDown, ThumbsUp, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { addNote, proposalLink, sendFeedback, setDealValue, uploadProposal } from '@/app/(app)/leads/[id]/actions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input, Select, Textarea } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { FEEDBACK_REASONS, type FeedbackReason } from '@/lib/feedback'
import { formatInr } from '@/lib/format'
import { formatMoney, type DealCurrency, type LeadMoney } from '@/lib/outcomes'
import { RetainerFields } from './outcome-dialogs'

function useRun() {
  const [pending, start] = useTransition()
  const run = (fn: () => Promise<{ ok: boolean; message?: string }>, onOk?: () => void) =>
    start(async () => {
      const r = await fn()
      if (r.ok) {
        toast(r.message ?? 'Saved')
        onOk?.()
      } else toast.error(r.message ?? 'Could not save. Try again.')
    })
  return { pending, run }
}

export function NotesCard({ leadId, summary, canEdit }: { leadId: string; summary: string | null; canEdit: boolean }) {
  const { pending, run } = useRun()
  const [text, setText] = useState('')
  return (
    <Card aria-labelledby="notes-title" data-tour="lead-notes">
      <CardHeader id="notes-title" title="Notes" description="The newest note is also shown in the sheet's Notes column." />
      <CardBody className="flex flex-col gap-3">
        {summary ? <p className="rounded-xl bg-surface-2 px-3.5 py-2.5 text-base whitespace-pre-line text-tx-2">{summary}</p> : <p className="text-base text-tx-3">No notes yet.</p>}
        {canEdit ? (
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              run(() => addNote({ leadId, text }), () => setText(''))
            }}
          >
            <label htmlFor="note-text" className="sr-only">
              New note
            </label>
            <Textarea id="note-text" rows={3} value={text} maxLength={1000} onChange={(e) => setText(e.currentTarget.value)} placeholder="What happened, what is next" />
            <div className="flex justify-end">
              <Button type="submit" size="sm" variant="primary" disabled={!text.trim()} loading={pending}>
                Add note
              </Button>
            </div>
          </form>
        ) : null}
      </CardBody>
    </Card>
  )
}

const asText = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

export function DealCard({
  leadId,
  money,
  country,
  proposals,
}: {
  leadId: string
  money: LeadMoney | null
  country: string | null
  proposals: { path: string; name: string; size: number }[]
}) {
  const { pending, run } = useRun()
  const saved = { deal: asText(money?.deal), retainer: asText(money?.retainer), currency: money?.currency ?? 'INR' }
  const [amount, setAmount] = useState(saved.deal)
  const [retainer, setRetainer] = useState(saved.retainer)
  const [currency, setCurrency] = useState<DealCurrency>(saved.currency)
  const dirty = amount !== saved.deal || retainer !== saved.retainer || currency !== saved.currency
  const summary = [money?.deal != null ? formatInr(money.deal) : '', money?.retainer != null ? `${formatMoney(money.retainer, money.currency)} a month` : '']
    .filter(Boolean)
    .join(' · ')
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, startUpload] = useTransition()
  const foreign = country && country.trim().toLowerCase() !== 'in'
  return (
    <Card aria-labelledby="deal-title" data-tour="lead-deal">
      <CardHeader id="deal-title" title="Deal" description="Admins only. Callers never see this card." />
      <CardBody className="flex flex-col gap-4">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => setDealValue({ leadId, value: amount, retainer, currency }))
          }}
        >
          <Field label="Deal value (₹)" hint={foreign ? "Foreign client: record the amount in rupees at the day's rate." : undefined}>
            {({ id, describedBy }) => (
              <Input id={id} aria-describedby={describedBy} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.currentTarget.value.replace(/[^\d.]/g, ''))} placeholder="150000" />
            )}
          </Field>
          <RetainerFields retainer={retainer} currency={currency} onRetainer={setRetainer} onCurrency={setCurrency} />
          <div className="flex items-center justify-between gap-2">
            <p className="min-w-0 text-sm text-green-800">{summary}</p>
            <Button type="submit" variant="primary" loading={pending} disabled={!dirty}>
              Save
            </Button>
          </div>
        </form>

        <div className="border-t border-line-2 pt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium text-tx-2">Proposals</span>
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
                  const r = await uploadProposal(leadId, fd)
                  if (r.ok) toast(r.message ?? 'Uploaded')
                  else toast.error(r.message)
                  if (fileRef.current) fileRef.current.value = ''
                })
              }}
            />
            <Button size="sm" variant="secondary" loading={uploading} onClick={() => fileRef.current?.click()}>
              <Upload aria-hidden />
              Upload
            </Button>
          </div>
          {proposals.length ? (
            <ul className="flex flex-col gap-1">
              {proposals.map((p) => (
                <li key={p.path}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1.5 text-left text-base text-indigo-800 hover:bg-surface-2"
                    onClick={async () => {
                      const r = await proposalLink(p.path)
                      // The signed link answers with a download, so the page itself stays put.
                      if (r.ok && r.data) window.location.assign(r.data)
                      else toast.error(r.ok ? 'Could not open the file.' : r.message)
                    }}
                  >
                    <FileText aria-hidden className="size-4 shrink-0" />
                    <span className="truncate">{p.name}</span>
                    {p.size ? <span className="ml-auto shrink-0 text-xs text-tx-3">{Math.max(1, Math.round(p.size / 1024))} KB</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-tx-3">PDF or Word, up to 10 MB. Stored privately.</p>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

export function FeedbackCard({ leadId, mine }: { leadId: string; mine: { rating: number; reason: string | null } | null }) {
  const { pending, run } = useRun()
  const [rating, setRating] = useState<1 | -1 | null>(mine ? (mine.rating > 0 ? 1 : -1) : null)
  const [reason, setReason] = useState<FeedbackReason>((mine?.reason as FeedbackReason) ?? 'Great lead')
  return (
    <Card aria-labelledby="feedback-title">
      <CardHeader id="feedback-title" title="Lead quality" description="Your vote trains the scoring." />
      <CardBody className="flex flex-col gap-3">
        <div className="flex gap-2" role="group" aria-label="Rate this lead">
          {([1, -1] as const).map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={rating === r}
              onClick={() => {
                setRating(r)
                setReason(r === 1 ? 'Great lead' : 'No real need')
              }}
              className={cn(
                'flex h-10 flex-1 items-center justify-center gap-2 rounded-full border text-base transition-colors',
                rating === r ? (r === 1 ? 'border-green-700 bg-green-50 text-green-800' : 'border-red-300 bg-red-50 text-red-600') : 'border-line text-tx-2 hover:bg-surface-2',
              )}
            >
              {r === 1 ? <ThumbsUp aria-hidden className="size-4" /> : <ThumbsDown aria-hidden className="size-4" />}
              {r === 1 ? 'Good lead' : 'Not good'}
            </button>
          ))}
        </div>
        {rating !== null ? (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              run(() => sendFeedback({ leadId, rating, reason }))
            }}
          >
            <div className="min-w-0 flex-1">
              <label htmlFor="feedback-reason" className="mb-1 block text-sm text-tx-3">
                Reason
              </label>
              <Select id="feedback-reason" value={reason} onChange={(e) => setReason(e.currentTarget.value as FeedbackReason)}>
                {FEEDBACK_REASONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </div>
            <Button type="submit" variant="primary" loading={pending}>
              Send
            </Button>
          </form>
        ) : null}
      </CardBody>
    </Card>
  )
}
