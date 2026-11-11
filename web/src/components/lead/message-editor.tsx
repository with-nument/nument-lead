'use client'

import { useId, useMemo, useState, useTransition } from 'react'
import { ArrowLeftRight, Check, CircleAlert, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { markFollowupSent } from '@/app/(app)/actions'
import { requestRegeneration, saveMessage, switchToAlternate } from '@/app/(app)/leads/[id]/actions'
import { Tag } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { CopyButton } from '@/components/ui/copy-button'
import { Textarea } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { countWords, lintMessage, type MessageKind } from '@/lib/lint'
import { ContactButtons } from './contact-actions'
import { useLeadActions } from './use-lead-actions'

type Target = { phone: string | null; phoneType: string | null; email: string | null }

function LintResult({ text, kind, id }: { text: string; kind: MessageKind; id: string }) {
  const problems = useMemo(() => (text.trim() ? lintMessage(text.trim(), kind) : []), [text, kind])
  if (!text.trim()) return <p id={id} className="text-sm text-tx-3">Empty</p>
  return problems.length ? (
    <ul id={id} className="flex flex-col gap-1 text-sm text-bad" aria-live="polite">
      {problems.map((p) => (
        <li key={p} className="flex items-start gap-1.5">
          <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {p}
        </li>
      ))}
    </ul>
  ) : (
    <p id={id} className="flex items-center gap-1.5 text-sm text-ok" aria-live="polite">
      <Check aria-hidden className="size-3.5" />
      Looks good · {countWords(text)} words
    </p>
  )
}

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
  label: string
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
      <label htmlFor={id} className="text-sm font-medium text-tx-2">
        {label}
      </label>
      <Textarea
        id={id}
        value={text}
        readOnly={!canEdit}
        onChange={(e) => setText(e.currentTarget.value)}
        rows={kind === 'message' ? 5 : 3}
        aria-describedby={`${id}-lint`}
        aria-invalid={problems.length > 0 || undefined}
      />
      <LintResult text={text} kind={kind} id={`${id}-lint`} />
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {canEdit ? (
          <Button
            variant={dirty ? 'primary' : 'secondary'}
            size="sm"
            disabled={!dirty || problems.length > 0}
            loading={pending}
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
          </Button>
        ) : null}
        {text ? <CopyButton text={text} size="sm" variant="ghost" /> : null}
        {children?.(text, dirty)}
      </div>
    </div>
  )
}

export function MessageCard({
  leadId,
  message,
  messageAlt,
  regenRequestedAt,
  needsEdit,
  target,
  canEdit,
}: {
  leadId: string
  message: string
  messageAlt: string
  regenRequestedAt: string | null
  needsEdit: boolean
  target: Target
  canEdit: boolean
}) {
  const actions = useLeadActions()
  const [pending, start] = useTransition()
  const run = (fn: () => Promise<{ ok: boolean; message?: string }>) =>
    start(async () => {
      const r = await fn()
      if (r.ok) toast(r.message ?? 'Saved')
      else toast.error(r.message ?? 'Could not save. Try again.')
    })

  return (
    <Card aria-labelledby="message-title">
      <CardHeader
        id="message-title"
        title="Message"
        description="30 to 60 words, one question, no links, no dashes, no emojis."
        actions={
          <>
            {needsEdit ? <Tag tone="warn">Needs your edit</Tag> : null}
            {regenRequestedAt ? <Tag tone="indigo">New message requested</Tag> : null}
          </>
        }
      />
      <CardBody>
        <Editor leadId={leadId} kind="message" label="First message" initial={message} canEdit={canEdit}>
          {(text, dirty) =>
            canEdit ? (
              <>
                {messageAlt ? (
                  <Button size="sm" variant="ghost" disabled={pending} onClick={() => run(() => switchToAlternate(leadId))}>
                    <ArrowLeftRight aria-hidden />
                    Use alternate
                  </Button>
                ) : null}
                <Button size="sm" variant="ghost" disabled={pending || Boolean(regenRequestedAt)} onClick={() => run(() => requestRegeneration(leadId))}>
                  <RefreshCw aria-hidden />
                  Regenerate
                </Button>
                <span className={cn('basis-full sm:basis-auto sm:ml-auto')} />
                <ContactButtons
                  target={{ ...target, message: text }}
                  disabled={dirty}
                  onOpen={(channel) => actions.markSent(leadId, channel)}
                />
              </>
            ) : null
          }
        </Editor>
        {messageAlt ? (
          <details className="mt-5 rounded-xl border border-line-2 px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-tx-2">Alternate message</summary>
            <div className="mt-3">
              <Editor leadId={leadId} kind="message_alt" label="Alternate" initial={messageAlt} canEdit={canEdit} />
            </div>
          </details>
        ) : null}
      </CardBody>
    </Card>
  )
}

export function FollowupsCard({
  leadId,
  d3,
  d7,
  d3SentOn,
  d7SentOn,
  target,
  canEdit,
}: {
  leadId: string
  d3: string
  d7: string
  d3SentOn: string | null
  d7SentOn: string | null
  target: Target
  canEdit: boolean
}) {
  const [, start] = useTransition()
  const send = (which: 'd3' | 'd7', channel: 'web' | 'app' | 'call' | 'email' | 'manual') =>
    start(async () => {
      const r = await markFollowupSent({ leadId, which, channel })
      if (r.ok) toast(r.message ?? 'Saved')
      else toast.error(r.message)
    })
  const block = (which: 'd3' | 'd7', text: string, sentOn: string | null, label: string) => (
    <Editor leadId={leadId} kind={which === 'd3' ? 'followup_d3' : 'followup_d7'} label={label} initial={text} canEdit={canEdit}>
      {(current, dirty) =>
        sentOn ? (
          <span className="ml-auto text-sm text-tx-3">Sent {sentOn}</span>
        ) : canEdit && current ? (
          <>
            <span className="basis-full sm:basis-auto sm:ml-auto" />
            <ContactButtons target={{ ...target, message: current }} disabled={dirty} onOpen={(channel) => send(which, channel)} />
          </>
        ) : null
      }
    </Editor>
  )
  return (
    <Card aria-labelledby="followups-title">
      <CardHeader id="followups-title" title="Follow-ups" description="Sent only if there is no reply. Opening WhatsApp marks the follow-up as sent." />
      <CardBody className="flex flex-col gap-6">
        {block('d3', d3, d3SentOn, 'Day 3')}
        {block('d7', d7, d7SentOn, 'Day 7')}
      </CardBody>
    </Card>
  )
}
