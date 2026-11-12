'use client'

import { useRef, useState, useTransition } from 'react'
import { FileText, ThumbsDown, ThumbsUp, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { addNote, proposalLink, sendFeedback, setDealValue, uploadProposal } from '@/app/(app)/leads/[id]/actions'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Select, Textarea } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { FEEDBACK_REASONS, type FeedbackReason } from '@/lib/feedback'
import { formatInr } from '@/lib/format'

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
    <Card aria-labelledby="notes-title">
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

export function DealCard({
  leadId,
  value,
  country,
  proposals,
}: {
  leadId: string
  value: number | null
  country: string | null
  proposals: { path: string; name: string; size: number }[]
}) {
  const { pending, run } = useRun()
  const [amount, setAmount] = useState(value === null ? '' : String(value))
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, startUpload] = useTransition()
  const foreign = country && country.trim().toLowerCase() !== 'in'
  return (
    <Card aria-labelledby="deal-title">
      <CardHeader id="deal-title" title="Deal" description="Admins only. Callers never see this card." />
      <CardBody className="flex flex-col gap-4">
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => setDealValue({ leadId, value: amount }))
          }}
        >
          <div className="min-w-0 flex-1">
            <label htmlFor="deal-value" className="mb-1 block text-sm font-medium text-tx-2">
              Deal value (₹)
            </label>
            <Input id="deal-value" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.currentTarget.value.replace(/[^\d.]/g, ''))} placeholder="150000" />
          </div>
          <Button type="submit" variant="primary" loading={pending} disabled={amount === (value === null ? '' : String(value))}>
            Save
          </Button>
        </form>
        {value !== null ? <p className="-mt-2 text-sm text-green-800">{formatInr(value)}</p> : null}
        {foreign ? <p className="-mt-2 text-xs text-tx-3">Foreign client: record the amount in rupees at the day&apos;s rate.</p> : null}

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
