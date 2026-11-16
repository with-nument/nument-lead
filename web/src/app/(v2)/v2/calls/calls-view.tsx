'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState, useTransition } from 'react'
import { ArrowRight, Check, ChevronLeft, ChevronRight, Phone, Video } from 'lucide-react'
import { updateStage } from '@/app/(app)/leads/[id]/actions'
import { Button, buttonClass } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { EmptyState } from '@/components/ui2/empty-state'
import { stageLabel } from '@/components/ui2/stage-label'
import { toast } from '@/components/ui2/toast'
import { daysBetween, formatTime, formatWeekday, istDate, relativeAge } from '@/lib/dates'
import { initials } from '@/lib/format'
import { rangeText, shortWhen, type Call, type CallsPage } from '@/lib/queries/email-data'
import type { Stage } from '@/lib/stages'
import { useHydrated } from '@/lib/use-hydrated'
import { useUndo } from '../inbox/use-undo'
import { saveCallNotes } from './actions'

type Group = 'today' | 'upcoming' | 'earlier'

const GROUP_LABEL: Record<Group, string> = { today: 'Today', upcoming: 'Coming up', earlier: 'Earlier' }

const minutesBetween = (a: string | null, b: string | null) => (a && b ? Math.round((Date.parse(b) - Date.parse(a)) / 60_000) : null)

function whereOf(location: string | null) {
  if (!location) return null
  if (location.includes('meet.google.')) return 'Google Meet'
  if (location.includes('zoom.')) return 'Zoom'
  if (location.includes('cal.com/video') || location.includes('cal.video')) return 'Cal Video'
  if (location.includes('teams.microsoft.')) return 'Teams'
  return 'Video call'
}

function untilText(iso: string, now: Date) {
  const mins = Math.round((Date.parse(iso) - now.getTime()) / 60_000)
  if (mins <= 0) return mins > -60 ? 'now' : ''
  if (mins < 60) return `in ${mins} min`
  return `in ${Math.round(mins / 60)} h`
}

/** "Tue" within the coming week, "Tomorrow", else "12 Nov". */
function dayText(iso: string, now: Date) {
  const days = daysBetween(istDate(now), istDate(iso))
  if (days === 1) return 'Tomorrow'
  return days > 1 && days < 7 ? formatWeekday(iso).split(' ')[0]! : shortWhen(iso, now)
}

const NOTES_KEY = (leadId: string) => `nl:call-notes:${leadId}`
const readLocal = (key: string) => {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}
const writeLocal = (key: string, value: string | null) => {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    /* private window or storage blocked: the notes still save to the database */
  }
}

function SoftTile({ text, className }: { text: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cx('grid shrink-0 place-items-center rounded-[12px] bg-fill-1 font-semibold text-label-2 hairline-ring', className)}
    >
      {text}
    </span>
  )
}

export function CallsView({ calls, canAct }: { calls: CallsPage; canAct: boolean }) {
  const all = useMemo(
    () => [
      ...calls.today.map((c) => ({ c, g: 'today' as Group })),
      ...calls.upcoming.map((c) => ({ c, g: 'upcoming' as Group })),
      ...calls.earlier.map((c) => ({ c, g: 'earlier' as Group })),
    ],
    [calls],
  )
  const [selected, setSelected] = useState<string | null>(all[0]?.c.leadId ?? null)
  const [phoneOpen, setPhoneOpen] = useState(false)
  const [showEarlier, setShowEarlier] = useState(calls.today.length + calls.upcoming.length === 0)
  const [stages, setStages] = useState<Record<string, string>>({})
  const [now] = useState(() => new Date())
  const { pending, schedule, undo, secondsLeft } = useUndo()

  const current = all.find((x) => x.c.leadId === selected)?.c ?? all[0]?.c
  const open = (id: string) => {
    setSelected(id)
    setPhoneOpen(true)
  }

  // J/K move through the calls.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.metaKey || e.ctrlKey || e.altKey || (t && ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return
      const k = e.key.toLowerCase()
      if (k !== 'j' && k !== 'k') return
      const visible = all.filter((x) => x.g !== 'earlier' || showEarlier)
      const i = visible.findIndex((x) => x.c.leadId === current?.leadId)
      const next = visible[Math.min(visible.length - 1, Math.max(0, i + (k === 'j' ? 1 : -1)))]
      if (next) setSelected(next.c.leadId)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [all, current, showEarlier])

  const outcome = (call: Call, stage: Stage, label: string) => {
    const before = stages[call.leadId] ?? call.stage ?? ''
    setStages((s) => ({ ...s, [call.leadId]: stage }))
    schedule({
      id: `stage:${call.leadId}`,
      label: `${label}: ${call.contactName ?? call.company}`,
      revert: () => setStages((s) => ({ ...s, [call.leadId]: before })),
      commit: async () => {
        const res = await updateStage({ leadId: call.leadId, stage })
        if (!res.ok) {
          setStages((s) => ({ ...s, [call.leadId]: before }))
          toast.error(res.message)
        }
      },
    })
  }

  const row = (c: Call, g: Group) => {
    const isCurrent = c.leadId === current?.leadId
    const sub = [c.company, c.booking?.kind === 'cancelled' ? 'cancelled' : null].filter(Boolean).join(' · ')
    return (
      <li key={c.leadId}>
        <button
          type="button"
          onClick={() => open(c.leadId)}
          aria-current={isCurrent ? 'true' : undefined}
          className={cx(
            'relative flex w-full items-center gap-4 py-4 pr-4 pl-4 text-left transition-colors hairline-t sm:px-6',
            isCurrent ? 'lg:bg-fill-3' : 'hover:bg-fill-3',
          )}
        >
          {isCurrent ? <span aria-hidden className="absolute inset-y-0 left-0 hidden w-[3px] bg-label-3 lg:block" /> : null}
          <span className="flex w-[78px] shrink-0 flex-col">
            <span className="text-[17px] font-medium text-label-1 tabular-nums lg:text-[16px]">{formatTime(c.meetingAt)}</span>
            <span className="text-[14px] text-label-3">
              {g === 'today' ? untilText(c.meetingAt, now) : g === 'upcoming' ? dayText(c.meetingAt, now) : shortWhen(c.meetingAt, now)}
            </span>
          </span>
          <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-fill-1 text-[12px] font-semibold text-label-2 hairline-ring">
            {initials(c.contactName ?? c.company)}
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-[17px] font-medium text-label-1 lg:text-[16px]">{c.contactName ?? c.company}</span>
            <span className="truncate text-[15px] text-label-3">{sub}</span>
          </span>
        </button>
      </li>
    )
  }

  const empty = all.length === 0

  return (
    <div className="lg:-mb-20 lg:grid lg:h-dvh lg:grid-cols-[minmax(320px,4fr)_7fr] lg:gap-6 lg:p-6 xl:grid-cols-[minmax(360px,500px)_1fr]">
      <section aria-label="Calls" className={cx('flex min-h-0 flex-col lg:material-panel lg:overflow-hidden lg:rounded-panel', phoneOpen && 'hidden lg:flex')}>
        <header className="px-4 pt-[max(12px,env(safe-area-inset-top))] pb-2 sm:px-6 lg:pt-6">
          <h1 className="type-large-title text-label-1">Calls</h1>
        </header>
        {pending.length ? (
          <div>
            {pending.map((p) => (
              <div key={p.id} role="status" className="hairline-t flex items-center gap-3 bg-fill-3 px-4 py-2.5 text-[14px] sm:px-6">
                <span className="min-w-0 flex-1 truncate text-label-2">{p.label}</span>
                <span className="shrink-0 text-label-3 tabular-nums">{secondsLeft(p)} s</span>
                <button type="button" onClick={() => undo(p.id)} className="shrink-0 rounded-[6px] px-2 py-1 font-semibold text-label-1 hover:bg-fill-2">
                  Undo
                </button>
              </div>
            ))}
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto pb-6">
          {empty ? (
            <EmptyState icon={<Phone />} title="No calls booked">
              When someone books a call from an email, it shows up here with a brief an hour before.
            </EmptyState>
          ) : (
            (['today', 'upcoming'] as const).map((g) =>
              calls[g].length ? (
                <div key={g}>
                  <h2 className="px-4 pt-5 pb-2 text-[14px] text-label-3 sm:px-6">{GROUP_LABEL[g]}</h2>
                  <ul role="list" className="hairline-b">
                    {calls[g].map((c) => row(c, g))}
                  </ul>
                </div>
              ) : null,
            )
          )}
          {!empty && calls.today.length === 0 ? <p className="px-4 pt-5 text-[15px] text-label-3 sm:px-6">No calls today.</p> : null}
          {calls.earlier.length ? (
            <div>
              <h2 className="px-4 pt-6 pb-2 text-[14px] text-label-3 sm:px-6">{GROUP_LABEL.earlier}</h2>
              <button
                type="button"
                aria-expanded={showEarlier}
                onClick={() => setShowEarlier((v) => !v)}
                className="hairline-t flex w-full items-center gap-3 px-4 py-4 text-left text-[16px] text-label-2 hover:bg-fill-3 sm:px-6"
              >
                <ChevronRight aria-hidden className={cx('size-4 text-label-3 transition-transform', showEarlier && 'rotate-90')} />
                <span className="flex-1">Last 30 days</span>
                <span className="text-label-3">
                  {calls.earlier.length} {calls.earlier.length === 1 ? 'call' : 'calls'}
                </span>
              </button>
              {showEarlier ? <ul role="list">{calls.earlier.map((c) => row(c, 'earlier'))}</ul> : null}
            </div>
          ) : null}
        </div>
      </section>

      <section aria-label="Call" className={cx('min-h-0 flex-col lg:material-panel lg:flex lg:overflow-hidden lg:rounded-panel', phoneOpen ? 'flex' : 'hidden')}>
        {current ? (
          <CallDetail
            key={current.leadId}
            call={current}
            stage={stages[current.leadId] ?? current.stage}
            now={now}
            canAct={canAct}
            onBack={() => setPhoneOpen(false)}
            onOutcome={outcome}
          />
        ) : (
          <EmptyState icon={<Phone />} title="No call selected" className="m-auto">
            Booked calls appear on the left.
          </EmptyState>
        )}
      </section>
    </div>
  )
}

function CallDetail({
  call: c,
  stage,
  now,
  canAct,
  onBack,
  onOutcome,
}: {
  call: Call
  stage: string | null
  now: Date
  canAct: boolean
  onBack: () => void
  onOutcome: (call: Call, stage: Stage, label: string) => void
}) {
  const saved = c.proposal?.callNotes ?? ''
  const [notes, setNotes] = useState(saved)
  const [savedNotes, setSavedNotes] = useState(saved)
  const [saving, startSaving] = useTransition()
  const brief = c.brief?.content ?? null
  const isToday = istDate(c.meetingAt) === istDate(now)
  const mins = minutesBetween(c.booking?.start ?? null, c.booking?.end ?? null)
  const where = whereOf(c.booking?.location ?? null)
  const joinUrl = c.booking?.location && c.booking.location.startsWith('https://') ? c.booking.location : null

  // An unsaved draft of the notes survives a reload (this browser only): offered back, never applied silently.
  const hydrated = useHydrated()
  const local = hydrated ? readLocal(NOTES_KEY(c.leadId)) : null
  const canRestore = !!local && local.trim() !== notes.trim() && local.trim() !== savedNotes.trim()

  const dirty = notes.trim() !== savedNotes.trim()

  const save = (then?: () => void) => {
    if (!notes.trim()) {
      if (then) toast.error('Write a few notes first, so the proposal has something to go on.')
      return
    }
    startSaving(async () => {
      const res = await saveCallNotes({ leadId: c.leadId, notes })
      if (!res.ok) {
        toast.error(res.message)
        return
      }
      setSavedNotes(notes)
      writeLocal(NOTES_KEY(c.leadId), null)
      toast.success(res.message ?? 'Notes saved')
      then?.()
    })
  }

  const when = [
    `${isToday ? 'Today' : shortWhen(c.meetingAt, now)}, ${formatTime(c.meetingAt)}${c.booking?.end ? ` to ${formatTime(c.booking.end)}` : ''}`,
    where,
    mins ? `${mins} minutes` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const goodToKnow = [
    ...(brief?.risks ?? []),
    c.plan && c.plan.views > 0
      ? `${c.contactName?.split(/\s+/)[0] ?? 'They'} viewed the plan page ${c.plan.views === 1 ? 'once' : c.plan.views === 2 ? 'twice' : `${c.plan.views} times`}${c.plan.lastViewedAt ? `, last ${relativeAge(c.plan.lastViewedAt, now)}` : ''}.`
      : null,
  ].filter((x): x is string => !!x)

  return (
    <>
      <div className="flex h-11 shrink-0 items-center px-2 pt-[env(safe-area-inset-top)] lg:hidden">
        <button type="button" onClick={onBack} className="flex h-11 items-center gap-0.5 px-2 text-[17px] text-label-1">
          <ChevronLeft aria-hidden className="size-6" />
          Calls
        </button>
      </div>
      <header className="flex shrink-0 flex-wrap items-center gap-4 px-4 pt-2 pb-4 sm:px-6 lg:hairline-b lg:px-8 lg:py-6">
        <SoftTile text={initials(c.company)} className="size-12 text-[17px]" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[22px] leading-tight font-semibold text-label-1">
            {c.contactName ? `${c.contactName} · ${c.company}` : c.company}
          </h2>
          <p className="mt-0.5 text-[15px] text-label-3">{when}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href={`/leads/${c.leadId}`} className={cx(buttonClass('plain'), 'text-label-1')}>
            Open lead
            <ArrowRight aria-hidden />
          </Link>
          {joinUrl && c.booking?.kind !== 'cancelled' ? (
            <a href={joinUrl} target="_blank" rel="noreferrer noopener" className={cx(buttonClass('primary'), 'lg:h-11 lg:px-6 lg:text-[16px]')}>
              <Video aria-hidden />
              Join call
            </a>
          ) : null}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-48 sm:px-6 lg:px-8 lg:pt-6 lg:pb-8">
        {brief ? (
          <>
            <p className="text-[14px] text-label-3">Pre-call brief{c.brief?.at ? ` · prepared ${formatTime(c.brief.at)}${istDate(c.brief.at) === istDate(now) ? '' : `, ${shortWhen(c.brief.at, now)}`}` : ''}</p>
            <p className="mt-3 text-[20px] leading-[1.45] text-label-1 lg:text-[22px]">{brief.summary}</p>
            <div className="mt-7 grid gap-7 md:grid-cols-2">
              <div>
                <h3 className="text-[14px] text-label-3">What they need</h3>
                <ul className="mt-2 flex list-disc flex-col gap-2 pl-5 text-[16px] text-label-1">
                  {brief.whatTheyNeed.map((x, k) => (
                    <li key={k}>{x}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="text-[14px] text-label-3">Ask them</h3>
                <ol className="mt-2 flex list-decimal flex-col gap-2 pl-5 text-[16px] text-label-1">
                  {brief.questions.map((x, k) => (
                    <li key={k}>{x}</li>
                  ))}
                </ol>
              </div>
            </div>
          </>
        ) : (
          <p className="rounded-[14px] bg-fill-1 px-5 py-4 text-[15px] text-label-2">
            {c.booking?.kind === 'cancelled'
              ? 'This call was cancelled.'
              : isToday || Date.parse(c.meetingAt) > now.getTime()
                ? 'The brief arrives about an hour before the call, by email and here.'
                : 'No brief was written for this call.'}
          </p>
        )}

        {c.booking?.notes ? (
          <div className="mt-7">
            <h3 className="text-[14px] text-label-3">What they wrote when booking</h3>
            <p className="mt-2 text-[16px] leading-[1.55] text-label-1">{c.booking.notes}</p>
          </div>
        ) : null}

        {c.offer ? (
          <div className="mt-7 rounded-[16px] bg-fill-1 px-6 py-5">
            <h3 className="text-[14px] text-label-3">What to offer</h3>
            <p className="mt-2 text-[16px] leading-[1.6] text-label-1">
              <span className="font-semibold">{c.offer.name}</span>
              {[c.offer.timeline ? `, ${c.offer.timeline.toLowerCase()}` : '', rangeText(c.offer.range) ? `, ${rangeText(c.offer.range)}` : ''].join('')}.{' '}
              {c.offer.promise}.
            </p>
            {c.offer.whyNow ? <p className="mt-2 text-[15px] leading-[1.55] text-label-2">Why now: {c.offer.whyNow}</p> : null}
          </div>
        ) : null}

        {goodToKnow.length ? (
          <div className="mt-7">
            <h3 className="text-[14px] text-label-3">Good to know</h3>
            <div className="mt-2 flex flex-col gap-1.5 text-[16px] leading-[1.6] text-label-2">
              {goodToKnow.map((x, k) => (
                <p key={k}>{x}</p>
              ))}
            </div>
          </div>
        ) : null}

        {canAct ? (
          <div className="mt-7">
            <div className="flex items-baseline justify-between">
              <label htmlFor={`notes-${c.leadId}`} className="text-[14px] text-label-3">
                Your notes
              </label>
              {canRestore ? (
                <button type="button" onClick={() => setNotes(local ?? '')} className="text-[13px] font-semibold text-label-2 hover:text-label-1">
                  Restore unsaved notes
                </button>
              ) : c.proposal?.drafted ? (
                <span className="text-[13px] text-label-3">Proposal drafted</span>
              ) : null}
            </div>
            <textarea
              id={`notes-${c.leadId}`}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value)
                writeLocal(NOTES_KEY(c.leadId), e.target.value)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  save()
                }
              }}
              rows={4}
              placeholder="Type during the call. Notes go straight into the proposal draft."
              className="mt-2 w-full resize-y rounded-[14px] bg-fill-3 p-4 text-[16px] leading-[1.55] text-label-1 shadow-[inset_0_0_0_1px_var(--ui-hairline)] outline-none placeholder:text-label-3 focus:shadow-[inset_0_0_0_1.5px_var(--ui-label-2)]"
            />
            {dirty ? (
              <div className="mt-2 flex items-center justify-end gap-3 text-[13px] text-label-3">
                <span>Not saved yet</span>
                <Button size="small" onClick={() => save()} disabled={saving} className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]">
                  Save notes
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {canAct && c.booking?.kind !== 'cancelled' ? (
        <footer className="material-bar hairline-t fixed inset-x-0 bottom-[calc(var(--ui-tabbar-h)+env(safe-area-inset-bottom))] z-20 flex shrink-0 flex-wrap items-center gap-2.5 px-4 py-3 lg:static lg:bg-transparent lg:px-8 lg:py-5 lg:backdrop-blur-none">
          <span className="hidden text-[15px] text-label-3 lg:inline">After the call</span>
          <div className="grid flex-1 grid-cols-3 gap-2.5 lg:flex lg:flex-none">
            <Button
              onClick={() => {
                if (dirty && notes.trim()) save()
                onOutcome(c, 'discovery_done', 'Call done')
              }}
              disabled={stage === 'discovery_done'}
              className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]"
            >
              <Check aria-hidden />
              Done
            </Button>
            <Button onClick={() => onOutcome(c, 'talking', 'No-show')} className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]">
              No-show
            </Button>
            <Button
              onClick={() => save(() => onOutcome(c, 'discovery_done', 'Proposal next'))}
              disabled={saving}
              className="bg-transparent shadow-[inset_0_0_0_1px_var(--ui-separator-strong)]"
            >
              Proposal next
            </Button>
          </div>
          <span className="ml-auto hidden text-[13px] text-label-3 xl:inline">
            {stage && stage !== 'discovery_booked' ? `Now: ${stageLabel(stage)} · ` : ''}Proposal next drafts it on the next engine run
          </span>
        </footer>
      ) : null}
    </>
  )
}

