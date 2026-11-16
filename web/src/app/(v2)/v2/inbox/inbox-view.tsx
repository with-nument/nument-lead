'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react'
import { ArrowRight, ChevronLeft, ChevronRight, Inbox as InboxIcon, Pencil, RotateCw } from 'lucide-react'
import { requestRegeneration } from '@/app/(app)/leads/[id]/actions'
import { Avatar } from '@/components/shell2/avatar'
import { Button, buttonClass } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { EmptyState } from '@/components/ui2/empty-state'
import { GradeMark } from '@/components/ui2/grade-mark'
import { stageLabel } from '@/components/ui2/stage-label'
import { toast } from '@/components/ui2/toast'
import { formatDate, formatDateTime } from '@/lib/dates'
import { initials } from '@/lib/format'
import {
  REPLY_LABEL,
  shortWhen,
  stepLabel,
  type DraftMessage,
  type InboxItem,
  type InboxPage,
  type InboxTab,
} from '@/lib/queries/email-data'
import { loadInboxPage, reviewMessage } from './actions'
import { useUndo } from './use-undo'

const TAB_LABEL: Record<InboxTab, string> = { replies: 'Replies', review: 'To review', done: 'Done' }

const DONE_LABEL: Record<string, string> = {
  approved: 'Approved, waiting to send',
  queued: 'Queued to send',
  sending: 'Sending',
  sent: 'Sent',
  failed: 'Could not send',
  cancelled: 'Not sent',
}

const who = (i: InboxItem) => i.contactName || i.toEmail || i.company || 'Unknown'

/** The first line or two of a message, for the list. */
const snippet = (text: string | null | undefined) =>
  (text ?? '')
    .replace(/^>.*$/gm, '')
    .replace(/\s+/g, ' ')
    .trim()

function typingInField(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  return !!t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))
}

function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cx(
        'hidden min-w-5 items-center justify-center rounded-[5px] px-1 text-[11px] leading-[18px] font-medium shadow-[inset_0_0_0_1px_currentColor] opacity-60 lg:inline-flex',
        className,
      )}
    >
      {children}
    </kbd>
  )
}

function Paragraphs({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
  return (
    <div className={cx('flex flex-col gap-3 whitespace-pre-line', className)}>
      {parts.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </div>
  )
}

type Edit = { subject: string; body: string }

export function InboxView({ initial, canAct }: { initial: InboxPage; canAct: boolean }) {
  const router = useRouter()
  const tab = initial.tab
  const [items, setItems] = useState<InboxItem[]>(initial.items)
  const [counts, setCounts] = useState(initial.counts)
  const [cursor, setCursor] = useState(initial.nextCursor)
  const [selected, setSelected] = useState<string | null>(initial.items[0]?.key ?? null)
  const [phoneOpen, setPhoneOpen] = useState(false)
  const [edit, setEdit] = useState<Edit | null>(null)
  const [busy, startBusy] = useTransition()
  const [tabPending, startTab] = useTransition()
  const { pending, schedule, undo, commitNow, secondsLeft } = useUndo()
  const paneRef = useRef<HTMLDivElement>(null)

  const index = Math.max(0, items.findIndex((i) => i.key === selected))
  const item = items.length ? items[index] : undefined

  const select = useCallback((key: string | null, open = false) => {
    setSelected(key)
    setEdit(null)
    if (open) setPhoneOpen(true)
    paneRef.current?.scrollTo({ top: 0 })
  }, [])

  const move = useCallback(
    (delta: number) => {
      if (!items.length) return
      const next = items[Math.min(items.length - 1, Math.max(0, index + delta))]
      if (next) {
        select(next.key)
        document.getElementById(`inbox-row-${next.key}`)?.scrollIntoView({ block: 'nearest' })
      }
    },
    [items, index, select],
  )

  const goTab = (t: InboxTab) => {
    if (t === tab) return
    startTab(() => router.push(t === 'replies' ? '?' : `?tab=${t}`, { scroll: false }))
  }

  /** Takes an item out of the list at once; Undo puts it back where it was. */
  const takeOut = useCallback(
    (target: InboxItem, label: string, commit: () => Promise<void>) => {
      const at = items.findIndex((i) => i.key === target.key)
      const rest = items.filter((i) => i.key !== target.key)
      setItems(rest)
      setCounts((c) => ({ ...c, [tab]: Math.max(0, c[tab] - 1), ...(tab !== 'done' ? { done: c.done + 1 } : {}) }))
      select(rest[Math.min(at, rest.length - 1)]?.key ?? null)
      setPhoneOpen(false)
      const restore = () => {
        setItems((now) => {
          if (now.some((i) => i.key === target.key)) return now
          const copy = [...now]
          copy.splice(Math.min(at, copy.length), 0, target)
          return copy
        })
        setCounts((c) => ({ ...c, [tab]: c[tab] + 1, ...(tab !== 'done' ? { done: Math.max(0, c.done - 1) } : {}) }))
        select(target.key)
      }
      schedule({
        id: target.key,
        label,
        revert: restore,
        commit: async () => {
          await commit().catch((e: unknown) => {
            restore()
            toast.error(e instanceof Error ? e.message : 'Could not save. Try again.')
          })
        },
      })
    },
    [items, schedule, select, tab],
  )

  const draftOf = (i: InboxItem | undefined): DraftMessage | null => (i && i.tab !== 'done' && i.draft && canAct ? i.draft : null)

  const approve = useCallback(() => {
    const target = item
    const d = draftOf(target)
    if (!target || !d) return
    const text = edit ? { subject: edit.subject, body: edit.body } : null
    if (text && !text.body.trim()) {
      toast.error('The email is empty.')
      return
    }
    setEdit(null)
    takeOut(target, `Approved ${d.step === null ? 'the reply' : stepLabel(d.step).toLowerCase() + ' email'} to ${who(target)}`, async () => {
      const res = await reviewMessage({
        messageId: d.id,
        leadId: target.leadId,
        action: 'approve',
        subject: text && d.step === 0 ? text.subject : null,
        body: text ? text.body : null,
      })
      if (!res.ok) throw new Error(res.message)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, edit, takeOut, canAct])

  const dismiss = () => {
    const target = item
    const d = draftOf(target)
    if (!target || !d) return
    setEdit(null)
    takeOut(target, `Will not send to ${who(target)}`, async () => {
      const res = await reviewMessage({ messageId: d.id, leadId: target.leadId, action: 'cancel' })
      if (!res.ok) throw new Error(res.message)
    })
  }

  const startEdit = useCallback(() => {
    const d = draftOf(item)
    if (!d) return
    setEdit((e) => e ?? { subject: d.subject ?? '', body: d.body })
    window.setTimeout(() => document.getElementById('inbox-composer-body')?.focus(), 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, canAct])

  const saveEdit = () => {
    const target = item
    const d = draftOf(target)
    if (!target || !d || !edit) return
    startBusy(async () => {
      const res = await reviewMessage({
        messageId: d.id,
        leadId: target.leadId,
        action: 'edit',
        subject: d.step === 0 ? edit.subject : null,
        body: edit.body,
      })
      if (!res.ok) {
        toast.error(res.message)
        return
      }
      const next = { ...d, subject: res.data?.subject ?? d.subject, body: res.data?.body ?? edit.body }
      setItems((all) => all.map((i) => (i.key === target.key ? { ...i, draft: next } : i)))
      setEdit(null)
      toast.success('Saved')
    })
  }

  const canRewrite = (i: InboxItem | undefined) => !!draftOf(i) && i?.draft?.step === 0

  const rewrite = useCallback(() => {
    const target = item
    if (!target || !canRewrite(target)) return
    startBusy(async () => {
      const res = await requestRegeneration(target.leadId)
      if (res.ok) toast('Asked for a new first email. The next engine run writes it and it comes back here.')
      else toast.error(res.message)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, canAct])

  // J/K move, A approve, E edit, R rewrite; Escape leaves the editor, Cmd/Ctrl+Enter saves it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      if (typingInField(e)) {
        if (e.key === 'Escape' && edit) setEdit(null)
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && edit) {
          e.preventDefault()
          approve()
        }
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const k = e.key.toLowerCase()
      const keys: Record<string, () => void> = {
        j: () => move(1),
        arrowdown: () => move(1),
        k: () => move(-1),
        arrowup: () => move(-1),
        a: approve,
        e: startEdit,
        r: rewrite,
      }
      if (k === 'escape' && phoneOpen) setPhoneOpen(false)
      const run = keys[k]
      if (run) {
        e.preventDefault()
        run()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [approve, edit, move, phoneOpen, rewrite, startEdit])

  const loadMore = () => {
    if (!cursor) return
    startBusy(async () => {
      const res = await loadInboxPage(tab, cursor)
      if (!res.ok || !res.data) {
        toast.error(res.ok ? 'Could not load more.' : res.message)
        return
      }
      const page = res.data
      setItems((all) => [...all, ...page.items.filter((i) => !all.some((a) => a.key === i.key))])
      setCursor(page.nextCursor)
    })
  }

  const tabs = useMemo(
    () =>
      (['replies', 'review', 'done'] as const).map((t) => (
        <button
          key={t}
          type="button"
          role="tab"
          aria-selected={t === tab}
          onClick={() => goTab(t)}
          className={cx(
            'flex h-9 items-center gap-1.5 rounded-[9px] px-3.5 text-[15px] transition-colors lg:h-8 lg:text-[14px]',
            t === tab ? 'bg-thumb font-semibold text-label-1 shadow-[var(--ui-shadow-thumb)]' : 'text-label-2 hover:text-label-1',
          )}
        >
          {TAB_LABEL[t]}
          {t !== 'done' && counts[t] > 0 ? <span className="text-[13px] font-normal text-label-3 tabular-nums">{counts[t]}</span> : null}
        </button>
      )),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tab, counts],
  )

  const list = (
    <section
      aria-label={TAB_LABEL[tab]}
      className={cx('flex min-h-0 flex-col lg:material-panel lg:overflow-hidden lg:rounded-panel', phoneOpen && 'hidden lg:flex')}
    >
      <header className="px-4 pt-[max(12px,env(safe-area-inset-top))] pb-4 sm:px-6 lg:px-6 lg:pt-6">
        <h1 className="type-large-title text-label-1">Inbox</h1>
        <div role="tablist" aria-label="Inbox" className="mt-4 inline-flex rounded-[11px] bg-fill-1 p-0.5">
          {tabs}
        </div>
      </header>
      {pending.length ? (
        <div className="flex flex-col">
          {pending.map((p) => (
            <div key={p.id} role="status" className="hairline-t flex items-center gap-3 bg-fill-3 px-4 py-2.5 text-[14px] sm:px-6">
              <span className="min-w-0 flex-1 truncate text-label-2">{p.label}</span>
              <span className="shrink-0 text-label-3 tabular-nums">{secondsLeft(p)} s</span>
              <button type="button" onClick={() => undo(p.id)} className="shrink-0 rounded-[6px] px-2 py-1 font-semibold text-label-1 hover:bg-fill-2">
                Undo
              </button>
              <button type="button" onClick={() => commitNow(p.id)} className="sr-only focus:not-sr-only">
                Send now
              </button>
            </div>
          ))}
        </div>
      ) : null}
      <div className={cx('min-h-0 flex-1 overflow-y-auto hairline-t', tabPending && 'opacity-60')}>
        {items.length === 0 ? (
          <EmptyState icon={<InboxIcon />} title={tab === 'replies' ? 'No replies waiting' : tab === 'review' ? 'Nothing to review' : 'Nothing here yet'}>
            {!canAct
              ? 'Email is for admins and callers. Ask an admin if you need it.'
              : tab === 'replies'
                ? 'When someone answers an email, it shows up here with a reply ready to approve.'
                : tab === 'review'
                  ? 'First emails that need your eyes before they go out wait here.'
                  : 'Emails you approve and the ones that went out are listed here.'}
          </EmptyState>
        ) : (
          <ul role="list">
            {items.map((i) => (
              <li key={i.key} id={`inbox-row-${i.key}`}>
                <Row item={i} current={i.key === item?.key} onOpen={() => select(i.key, true)} />
              </li>
            ))}
          </ul>
        )}
        {cursor ? (
          <div className="flex justify-center p-4">
            <Button size="small" onClick={loadMore} disabled={busy}>
              Show more
            </Button>
          </div>
        ) : null}
      </div>
      <footer className="hairline-t hidden items-center gap-5 px-6 py-3 text-[13px] text-label-3 lg:flex">
        <span className="flex items-center gap-1.5">
          <Kbd>J</Kbd>
          <Kbd>K</Kbd> move
        </span>
        {tab !== 'done' && canAct ? (
          <>
            <span className="flex items-center gap-1.5">
              <Kbd>A</Kbd> approve
            </span>
            <span className="flex items-center gap-1.5">
              <Kbd>E</Kbd> edit
            </span>
            <span className="flex items-center gap-1.5">
              <Kbd>R</Kbd> rewrite
            </span>
          </>
        ) : null}
      </footer>
    </section>
  )

  return (
    <div className="lg:-mb-20 lg:grid lg:h-dvh lg:grid-cols-[minmax(340px,5fr)_7fr] lg:gap-6 lg:p-6 xl:grid-cols-[minmax(380px,550px)_1fr]">
      {list}
      <section
        aria-label="Message"
        className={cx('min-h-0 flex-col lg:material-panel lg:flex lg:overflow-hidden lg:rounded-panel', phoneOpen ? 'flex' : 'hidden')}
      >
        {item ? (
          <Reading
            key={item.key}
            item={item}
            position={`${index + 1} of ${items.length}`}
            paneRef={paneRef}
            onBack={() => setPhoneOpen(false)}
            edit={edit}
            setEdit={setEdit}
            canAct={canAct}
            busy={busy}
            actions={{ approve, startEdit, saveEdit, rewrite, dismiss, canRewrite: canRewrite(item) }}
          />
        ) : (
          <EmptyState icon={<InboxIcon />} title="Nothing selected" className="m-auto">
            Pick a message on the left.
          </EmptyState>
        )}
      </section>
    </div>
  )
}

function Row({ item: i, current, onOpen }: { item: InboxItem; current: boolean; onOpen: () => void }) {
  const unread = i.tab !== 'done'
  const body = i.tab === 'replies' ? i.inbound?.body : i.draft?.body
  const meta =
    i.tab === 'replies'
      ? [REPLY_LABEL[i.inbound?.classification ?? ''] ?? 'Not sorted yet', i.draft ? 'reply drafted' : 'no draft yet'].join(' · ')
      : i.tab === 'review'
        ? [stepLabel(i.draft?.step ?? 0), i.draft?.subject ? `“${i.draft.subject}”` : null].filter(Boolean).join(' · ')
        : [DONE_LABEL[i.draft?.status ?? ''] ?? i.draft?.status, i.draft ? stepLabel(i.draft.step) : null].filter(Boolean).join(' · ')
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-current={current ? 'true' : undefined}
      className={cx(
        'relative flex w-full flex-col gap-1 py-4 pr-4 pl-9 text-left transition-colors hairline-b sm:pr-6 lg:pl-11',
        current ? 'lg:bg-fill-3' : 'hover:bg-fill-3',
        'focus-visible:-outline-offset-2',
      )}
    >
      {current ? <span aria-hidden className="absolute inset-y-0 left-0 hidden w-[3px] bg-label-3 lg:block" /> : null}
      {unread ? <span aria-label="Needs you" className="absolute top-[26px] left-4 size-[7px] rounded-full bg-label-2 lg:left-6" /> : null}
      <span className="flex items-baseline gap-2">
        <span className="truncate text-[17px] font-semibold text-label-1 lg:text-[16px]">{who(i)}</span>
        <span className="min-w-0 flex-1 truncate text-[15px] text-label-3">{i.company}</span>
        <span className="shrink-0 text-[14px] text-label-3 tabular-nums">{shortWhen(i.at)}</span>
      </span>
      <span className="line-clamp-2 text-[15px] leading-[1.45] text-label-2">{snippet(body) || 'No text'}</span>
      <span className="text-[13px] text-label-3">{meta}</span>
    </button>
  )
}

function Reading({
  item: i,
  position,
  paneRef,
  onBack,
  edit,
  setEdit,
  canAct,
  busy,
  actions,
}: {
  item: InboxItem
  position: string
  paneRef: React.RefObject<HTMLDivElement | null>
  onBack: () => void
  edit: Edit | null
  setEdit: (e: Edit | null) => void
  canAct: boolean
  busy: boolean
  actions: { approve: () => void; startEdit: () => void; saveEdit: () => void; rewrite: () => void; dismiss: () => void; canRewrite: boolean }
}) {
  const [showOurs, setShowOurs] = useState(false)
  const d = i.draft
  const actionable = canAct && i.tab !== 'done' && !!d
  const sub = [i.contactRole ? `${i.contactRole}, ${i.company}` : i.company, i.city, i.toEmail].filter(Boolean).join(' · ')
  const firstName = (i.contactName ?? '').split(/\s+/)[0]

  return (
    <>
      {/* Phone: back to the list */}
      <div className="flex h-11 shrink-0 items-center justify-between px-2 pt-[env(safe-area-inset-top)] lg:hidden">
        <button type="button" onClick={onBack} className="flex h-11 items-center gap-0.5 px-2 text-[17px] text-label-1">
          <ChevronLeft aria-hidden className="size-6" />
          Inbox
        </button>
        <span className="text-[15px] text-label-3">{position}</span>
        <span className="w-16" />
      </div>
      <header className="flex shrink-0 items-center gap-4 px-4 pt-2 pb-4 sm:px-6 lg:hairline-b lg:px-8 lg:py-5">
        <Avatar initials={initials(i.contactName ?? i.company)} size="large" className="hairline-ring text-label-2 lg:size-[60px] lg:text-[19px]" />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[22px] font-semibold text-label-1 lg:text-[21px]">{who(i)}</h2>
          <p className="truncate text-[15px] text-label-3">
            <span className="lg:hidden">
              {i.contactRole ? `${i.contactRole}, ${i.company}` : i.company} · {shortWhen(i.at)}
            </span>
            <span className="hidden lg:inline">{sub}</span>
          </p>
        </div>
        {i.grade ? <GradeMark grade={i.grade} size="large" /> : null}
        {i.stage ? <span className="hidden text-[15px] text-label-2 lg:inline">{stageLabel(i.stage)}</span> : null}
        <Link href={`/leads/${i.leadId}`} className={cx(buttonClass('secondary', 'regular'), 'hidden lg:inline-flex')}>
          Open lead
          <ArrowRight aria-hidden />
        </Link>
      </header>

      <div ref={paneRef} className="min-h-0 flex-1 overflow-y-auto px-4 pb-44 sm:px-6 lg:px-8 lg:pt-6 lg:pb-8">
        {i.lastOut && i.tab === 'replies' ? (
          <div className="mb-6 rounded-[14px] bg-fill-1">
            <button
              type="button"
              aria-expanded={showOurs}
              onClick={() => setShowOurs((v) => !v)}
              className="flex w-full items-center gap-3 px-4 py-3.5 text-left text-[15px]"
            >
              <ChevronRight aria-hidden className={cx('size-4 shrink-0 text-label-3 transition-transform', showOurs && 'rotate-90')} />
              <span className="font-semibold text-label-1">Our email</span>
              <span className="min-w-0 flex-1 truncate text-label-3">
                {stepLabel(i.lastOut.step)}
                {i.lastOut.subject ? ` · “${i.lastOut.subject}”` : ''}
              </span>
              {i.lastOut.at ? <span className="hidden shrink-0 text-[14px] text-label-3 sm:inline">{formatDate(i.lastOut.at)}</span> : null}
            </button>
            {showOurs ? <Paragraphs text={i.lastOut.body} className="px-11 pb-4 text-[15px] leading-[1.55] text-label-2" /> : null}
          </div>
        ) : null}

        {i.inbound ? (
          <article className="mb-8">
            <p className="mb-3 hidden items-baseline gap-2 lg:flex">
              <span className="text-[17px] font-semibold text-label-1">{who(i)}</span>
              {i.inbound.at ? <span className="text-[15px] text-label-3">{formatDateTime(i.inbound.at)}</span> : null}
            </p>
            <Paragraphs text={i.inbound.body || '(no text)'} className="text-[17px] leading-[1.6] text-label-1 lg:text-[18px]" />
          </article>
        ) : null}

        {d ? (
          <div className="rounded-[18px] bg-[var(--ui-panel-solid,white)] shadow-[inset_0_0_0_1px_var(--ui-hairline)]">
            <div className="hairline-b flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-5 py-3.5 lg:px-6">
              <span className="text-[16px] font-semibold text-label-1">
                {i.tab === 'done' ? (d.step === null ? 'Our reply' : `${stepLabel(d.step)} email`) : d.step === null ? 'Suggested reply' : `${stepLabel(d.step)} email`}
              </span>
              <span className="text-[14px] text-label-3">
                {i.tab === 'done'
                  ? `· ${DONE_LABEL[d.status] ?? d.status}${d.sentAt ? `, ${formatDateTime(d.sentAt)}` : ''}`
                  : d.step === null
                    ? `· written from ${firstName ? `${firstName}’s` : 'their'} email and the ${i.company} research`
                    : '· written from the research, waiting for your review'}
              </span>
            </div>
            <div className="px-5 py-5 lg:px-6">
              {edit ? (
                <div className="flex flex-col gap-3">
                  {d.step === 0 ? (
                    <label className="flex flex-col gap-1">
                      <span className="text-[13px] text-label-3">Subject</span>
                      <input
                        value={edit.subject}
                        onChange={(e) => setEdit({ ...edit, subject: e.target.value })}
                        className="h-11 rounded-[10px] bg-fill-3 px-3 text-[16px] text-label-1 shadow-[inset_0_0_0_1px_var(--ui-hairline)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--ui-label-1)]"
                      />
                    </label>
                  ) : null}
                  <label className="flex flex-col gap-1">
                    <span className="sr-only">Email text</span>
                    <textarea
                      id="inbox-composer-body"
                      value={edit.body}
                      onChange={(e) => setEdit({ ...edit, body: e.target.value })}
                      rows={Math.min(18, Math.max(8, edit.body.split('\n').length + 2))}
                      className="w-full resize-y rounded-[10px] bg-fill-3 p-3 text-[16px] leading-[1.6] text-label-1 shadow-[inset_0_0_0_1px_var(--ui-hairline)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--ui-label-1)]"
                    />
                  </label>
                </div>
              ) : (
                <>
                  {d.step === 0 && d.subject ? <p className="mb-3 text-[15px] text-label-3">Subject: {d.subject}</p> : null}
                  <Paragraphs text={d.body} className="text-[16px] leading-[1.65] text-label-1 lg:text-[17px]" />
                </>
              )}
              {d.error && i.tab === 'done' ? <p className="mt-3 text-[14px] text-label-3">{d.error}</p> : null}
            </div>
            {actionable ? (
              <div className="hidden flex-wrap items-center gap-3 px-6 pb-6 lg:flex">
                <Button variant="primary" onClick={actions.approve} className="h-11 px-5 text-[16px]">
                  {edit ? 'Save and send' : 'Approve and send'}
                  <Kbd className="ml-1">A</Kbd>
                </Button>
                {edit ? (
                  <Button onClick={actions.saveEdit} disabled={busy} className="h-11 shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]">
                    Save draft
                  </Button>
                ) : (
                  <Button onClick={actions.startEdit} className="h-11 bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]">
                    <Pencil aria-hidden />
                    Edit
                    <Kbd>E</Kbd>
                  </Button>
                )}
                <Button
                  variant="plain"
                  onClick={actions.rewrite}
                  disabled={busy || !actions.canRewrite}
                  title={actions.canRewrite ? 'Ask the engine for a new first email' : 'Only a first email can be rewritten by the engine. Edit this one instead.'}
                  className="h-11 text-label-1"
                >
                  <RotateCw aria-hidden />
                  Rewrite
                  <Kbd>R</Kbd>
                </Button>
                <span className="ml-auto flex items-center gap-3 text-[13px] text-label-3">
                  {edit ? (
                    <button type="button" onClick={() => setEdit(null)} className="hover:text-label-1">
                      Discard changes
                    </button>
                  ) : (
                    <button type="button" onClick={actions.dismiss} className="hover:text-label-1">
                      Don’t send
                    </button>
                  )}
                  <span>30 s to undo</span>
                </span>
              </div>
            ) : null}
          </div>
        ) : i.tab === 'replies' ? (
          <p className="rounded-[14px] bg-fill-1 px-5 py-4 text-[15px] text-label-2">
            No reply drafted yet. The engine drafts one on its next run; for a question it cannot answer, reply from the Nument mailbox.
          </p>
        ) : null}
      </div>

      {/* Phone: the actions stay at the bottom, above the tab bar */}
      {actionable ? (
        <div className="material-bar hairline-t fixed inset-x-0 bottom-[calc(var(--ui-tabbar-h)+env(safe-area-inset-bottom))] z-20 flex flex-col gap-2.5 px-4 py-3 lg:hidden">
          <Button variant="primary" size="large" onClick={actions.approve}>
            {edit ? 'Save and send' : 'Approve and send'}
          </Button>
          <div className="grid grid-cols-2 gap-2.5">
            {edit ? (
              <Button size="large" onClick={() => setEdit(null)} className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]">
                Discard
              </Button>
            ) : (
              <Button size="large" onClick={actions.startEdit} className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]">
                <Pencil aria-hidden />
                Edit
              </Button>
            )}
            <Button
              size="large"
              onClick={actions.rewrite}
              disabled={busy || !actions.canRewrite}
              className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]"
            >
              <RotateCw aria-hidden />
              Rewrite
            </Button>
          </div>
        </div>
      ) : null}
    </>
  )
}
