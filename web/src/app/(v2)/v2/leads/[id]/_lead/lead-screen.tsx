'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState, useTransition } from 'react'
import { ArrowRight, ChevronLeft, ChevronRight, Ellipsis, Globe, MapPin, UserRound } from 'lucide-react'
import { markContacted, markReplied, markWrongContact, skipLead, undoLeadChange, type PreviousState, type UndoKind } from '@/app/(app)/actions'
import { requestRegeneration } from '@/app/(app)/leads/[id]/actions'
import { buttonClass } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { SegmentedControl } from '@/components/ui2/segmented-control'
import { Sheet, SheetContent } from '@/components/ui2/sheet'
import { toast } from '@/components/ui2/toast'
import { canMarkReplied } from '@/lib/outcomes'
import { CLOSED_STAGES } from '@/lib/stages'
import { GradeLetter, Monogram, panel, plainClass, Status } from '../../_ui/marks'
import { useStageMove } from '../../_ui/stage-move'
import { UndoRow, useUndo } from '../../_ui/use-run'
import { Activity, type MyFeedback, type Proposal } from './activity'
import type { Channel } from './contact-buttons'
import { Conversation } from './conversation'
import { Inspector } from './inspector'
import { primaryActionFor, statusOf, type LeadView } from './model'
import { People } from './people'
import type { LeadExtras } from './types'
import { Why } from './why'

export type Tab = 'conversation' | 'why' | 'people' | 'activity'
const TABS: Tab[] = ['conversation', 'why', 'people', 'activity']

export type LeadScreenProps = {
  view: LeadView
  canEdit: boolean
  isAdmin: boolean
  includeUnverified: boolean
  team: { id: string; name: string }[]
  proposals: Proposal[]
  myFeedback: MyFeedback
  extras?: LeadExtras
  /** The segment to open first (from ?tab=). */
  initialTab?: Tab | null
}

type Outcome = { ok: boolean; message?: string; data?: PreviousState }

/** The v2 lead page: one next step in the header, then Conversation, Why, People and Activity. */
export function LeadScreen({ view, canEdit, isAdmin, includeUnverified, team, proposals, myFeedback, extras = {}, initialTab }: LeadScreenProps) {
  const thread = extras.thread ?? null
  const [tab, setTab] = useState<Tab>(initialTab && TABS.includes(initialTab) ? initialTab : thread?.suggestedReply ? 'conversation' : 'why')
  const [stage, setStage] = useState(view.stage)
  const [synced, setSynced] = useState(view.stage)
  if (synced !== view.stage) {
    // The server moved the lead (an action, Undo, another tab): show its stage.
    setSynced(view.stage)
    setStage(view.stage)
  }
  const [reply, setReply] = useState(thread?.suggestedReply?.body ?? '')
  const [details, setDetails] = useState(false)
  const [pending, start] = useTransition()
  const undo = useUndo()
  const stageMove = useStageMove({ isAdmin, undo, onLocal: (_, s) => setStage(s) })
  const now = useMemo(() => new Date(), [])

  const status = stage === view.stage ? view.status : statusOf({ stage, wa_at: null, meeting_at: null, last_activity_at: new Date().toISOString(), lost_reason: null }, now)
  const primary = primaryActionFor({ stage, canEdit, hasPendingReply: Boolean(thread?.suggestedReply) })
  const open = !(CLOSED_STAGES as readonly string[]).includes(stage)
  const lead = { id: view.id, stage, name: view.name, money: view.money, lostReason: view.lostReason }

  /** An outcome action (sent, replied, skip, wrong contact) with an optimistic stage and the inline Undo. */
  const outcome = (fn: () => Promise<Outcome>, kind: UndoKind, text: string, optimistic?: string) => {
    const before = stage
    if (optimistic) setStage(optimistic)
    start(async () => {
      const r = await fn()
      if (!r.ok) {
        setStage(before)
        toast.error(r.message ?? 'Could not save. Try again.')
        return
      }
      const previous = r.data
      if (previous)
        undo.offer(text, async () => {
          setStage(previous.stage)
          return undoLeadChange(view.id, previous, kind)
        })
      else toast(text)
    })
  }
  const markSent = (channel: Channel | 'manual') => outcome(() => markContacted(view.id, channel), 'sent', 'Marked as contacted', stage === 'new' ? 'contacted' : undefined)

  const runPrimary = () => {
    if (!primary || pending) return
    switch (primary.kind) {
      case 'approve': {
        const s = thread?.suggestedReply
        if (!s || !extras.approveReply) {
          setTab('conversation')
          return
        }
        if (!reply.trim()) {
          toast.error('Write the reply first.')
          return
        }
        start(async () => {
          const r = await extras.approveReply!({ leadId: view.id, messageId: s.messageId, body: reply })
          if (r.ok) toast(r.message ?? 'Reply approved')
          else toast.error(r.message)
        })
        return
      }
      case 'contacted':
        return markSent('manual')
      case 'replied':
        return outcome(() => markReplied(view.id), 'replied', 'Marked as replied', 'talking')
      case 'stage':
        return primary.to ? stageMove.move(lead, primary.to) : undefined
      default:
        return
    }
  }

  // A: the header action. Never while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return
      const t = e.target as HTMLElement | null
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
      if (e.key === 'a' || e.key === 'A') {
        if (primary?.kind === 'brief' && primary.href) window.location.assign(primary.href)
        else runPrimary()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const primaryButton = primary ? (
    primary.kind === 'brief' && primary.href ? (
      <Link href={primary.href} className={buttonClass('primary', 'large', 'lg:h-12 lg:w-auto lg:rounded-[14px] lg:px-5')} aria-keyshortcuts="A">
        {primary.label}
        <ArrowRight aria-hidden />
      </Link>
    ) : (
      <button type="button" onClick={runPrimary} disabled={pending || stageMove.pending} aria-keyshortcuts="A" className={buttonClass('primary', 'large', 'lg:h-12 lg:w-auto lg:rounded-[14px] lg:px-5')}>
        {primary.label}
        <ArrowRight aria-hidden />
      </button>
    )
  ) : null

  const more = (
    <Menu>
      <MenuTrigger aria-label="More actions" className={cx(plainClass('regular'), 'w-11 px-0 lg:w-[38px]')}>
        <Ellipsis aria-hidden />
      </MenuTrigger>
      <MenuContent>
        <MenuItem onSelect={() => setDetails(true)}>
          Details
        </MenuItem>
        {canEdit && primary?.kind !== 'replied' && canMarkReplied(stage) ? (
          <MenuItem onSelect={() => outcome(() => markReplied(view.id), 'replied', 'Marked as replied', 'talking')}>Mark replied</MenuItem>
        ) : null}
        {canEdit && primary?.kind !== 'contacted' && stage === 'new' ? <MenuItem onSelect={() => markSent('manual')}>Mark contacted</MenuItem> : null}
        {canEdit ? <MenuItem onSelect={() => setTab('activity')}>Change stage or next step</MenuItem> : null}
        {canEdit && open ? <MenuItem onSelect={() => outcome(() => skipLead(view.id), 'skip', 'Skipped for 7 days')}>Skip for 7 days</MenuItem> : null}
        {canEdit && !view.regenRequested ? (
          <MenuItem
            onSelect={() =>
              start(async () => {
                const r = await requestRegeneration(view.id)
                if (r.ok) toast(r.message ?? 'Requested')
                else toast.error(r.message)
              })
            }
          >
            Write a new message
          </MenuItem>
        ) : null}
        {view.website || view.mapsUrl ? <MenuSeparator /> : null}
        {view.website ? (
          <MenuItem asChild>
            <a href={view.website} target="_blank" rel="noopener noreferrer">
              <Globe aria-hidden />
              Open website
            </a>
          </MenuItem>
        ) : null}
        {view.mapsUrl ? (
          <MenuItem asChild>
            <a href={view.mapsUrl} target="_blank" rel="noopener noreferrer">
              <MapPin aria-hidden />
              Google listing
            </a>
          </MenuItem>
        ) : null}
        {canEdit && view.target.phone ? (
          <>
            <MenuSeparator />
            <MenuItem destructive onSelect={() => outcome(() => markWrongContact(view.id), 'wrong_contact', 'Marked as wrong contact. The number is now on Do not contact.', 'wrong_contact')}>
              Wrong contact
            </MenuItem>
          </>
        ) : null}
      </MenuContent>
    </Menu>
  )

  const meta = [
    view.place ? { icon: <MapPin aria-hidden />, text: view.place } : null,
    view.host ? { icon: <Globe aria-hidden />, text: view.host } : null,
    view.peopleCount ? { icon: <UserRound aria-hidden />, text: `${view.peopleCount} ${view.peopleCount === 1 ? 'person' : 'people'}` } : null,
  ].filter((m): m is { icon: React.ReactElement; text: string } => m !== null)


  let body: React.ReactNode
  if (tab === 'why') body = <Why view={view} offer={extras.offer} isAdmin={isAdmin} includeUnverified={includeUnverified} />
  else if (tab === 'people')
    body = (
      <People
        view={view}
        canEdit={canEdit}
        isAdmin={isAdmin}
        team={team}
        onOpen={(ch) => markSent(ch)}
        onWrong={() => outcome(() => markWrongContact(view.id), 'wrong_contact', 'Marked as wrong contact. The number is now on Do not contact.', 'wrong_contact')}
      />
    )
  else if (tab === 'activity')
    body = <Activity view={view} stage={stage} canEdit={canEdit} isAdmin={isAdmin} proposals={proposals} myFeedback={myFeedback} onStage={(to) => stageMove.move(lead, to)} />
  else body = <Conversation view={view} thread={thread} canEdit={canEdit} onOpen={(ch) => markSent(ch)} reply={reply} onReply={setReply} />

  return (
    <div className="mx-auto max-w-[1280px] px-4 pt-3 sm:px-6 lg:px-14 lg:pt-11">
      {/* Phone: back and More. Laptop: a breadcrumb. */}
      <div className="mb-4 flex items-center justify-between lg:hidden">
        <Link href="/leads" className="-ml-2 flex h-11 items-center gap-1 rounded-control pr-3 pl-1 text-[17px] text-label-1">
          <ChevronLeft aria-hidden className="size-5" />
          Leads
        </Link>
        {more}
      </div>
      <nav aria-label="Breadcrumb" className="mb-[18px] hidden items-center gap-1.5 text-[14px] text-label-3 lg:flex">
        <Link href="/leads" className="hover:text-label-1">
          Leads
        </Link>
        <ChevronRight aria-hidden className="size-3.5" />
        <span className="text-label-1">{view.name}</span>
      </nav>

      <header className="mb-5 lg:mb-[26px] lg:flex lg:items-center lg:gap-[18px]">
        <div className="flex min-w-0 flex-1 items-center gap-4 lg:gap-[18px]">
          <Monogram name={view.name} />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[28px] leading-[1.15] font-semibold tracking-[-0.025em] text-label-1 lg:text-[30px]">{view.name}</h1>
            <p className="type-subhead mt-0.5 truncate text-label-3 lg:hidden">{[view.place, view.host].filter(Boolean).join(' · ')}</p>
            {view.description ? <p className="mt-1 hidden text-[15.5px] text-label-2 lg:block">{view.description}</p> : null}
            {meta.length ? (
              <p className="mt-1.5 hidden flex-wrap gap-4 text-[14px] text-label-3 lg:flex">
                {meta.map((m) => (
                  <span key={m.text} className="inline-flex items-center gap-1.5 [&_svg]:size-3.5 [&_svg]:stroke-[1.75]">
                    {m.icon}
                    {m.text}
                  </span>
                ))}
              </p>
            ) : null}
          </div>
        </div>
        {view.description ? <p className="mt-4 text-[17px] leading-[1.45] text-label-2 lg:hidden">{view.description}</p> : null}
        <div className="mt-4 flex flex-col gap-4 lg:mt-0 lg:flex-row lg:items-center lg:gap-[14px]">
          <div className="flex items-center gap-5 text-[15px] text-label-2 lg:gap-[14px] lg:text-[13.5px]">
            <span className="inline-flex items-center gap-[7px]">
              <GradeLetter grade={view.grade} />
              Grade
            </span>
            <Status tone={status.tone}>{status.text}</Status>
          </div>
          {primaryButton ? <div className="lg:ml-2">{primaryButton}</div> : null}
          <div className="hidden lg:block">{more}</div>
        </div>
      </header>

      <UndoRow undo={undo} className="mb-4" />

      <SegmentedControl
        label="Lead sections"
        value={tab}
        onValueChange={setTab}
        className="mb-[18px] h-11 w-full lg:h-[38px] lg:w-[455px]"
        items={[
          { value: 'conversation', label: <><span className="lg:hidden">Chat</span><span className="hidden lg:inline">Conversation</span></> },
          { value: 'why', label: 'Why' },
          { value: 'people', label: 'People' },
          { value: 'activity', label: 'Activity' },
        ]}
      />

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className="min-w-0">{body}</div>
        <aside aria-label="Details" className={cx(panel, 'hidden lg:block')}>
          <Inspector view={view} thread={thread} planPage={extras.planPage} now={now} />
        </aside>
      </div>

      <Sheet open={details} onOpenChange={setDetails}>
        <SheetContent title={view.name} description="Contact, messages and the next step">
          <Inspector view={view} thread={thread} planPage={extras.planPage} now={now} flush />
        </SheetContent>
      </Sheet>
      {stageMove.dialogs}
    </div>
  )
}
