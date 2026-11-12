import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { Suspense } from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { ContactCard, type ContactView } from '@/components/lead/contact-card'
import { NextStepEditor, OwnerSelect, StageSelect } from '@/components/lead/lead-controls'
import { FactsCard, PagesCard, SignalsCard, TechCard, Timeline, WhyCard } from '@/components/lead/lead-sections'
import { FollowupsCard, MessageCard } from '@/components/lead/message-editor'
import { DealCard, FeedbackCard, NotesCard } from '@/components/lead/side-cards'
import { GradeBadge, StageBadge } from '@/components/ui/badge'
import { LeadSkeleton } from '@/components/skeletons'
import { early, requireUser } from '@/lib/auth'
import { formatDate } from '@/lib/dates'
import { hostOf, safeUrl } from '@/lib/format'
import { formatPhone } from '@/lib/phone'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { countryLabel } from '@/lib/signals'
import { getLeadDealValue, getLeadDetail, getProposals } from '@/lib/queries/lead'
import { getSegments, getTeam, segmentLabeler } from '@/lib/queries/shared'

export const metadata: Metadata = { title: 'Lead' }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export default function LeadPage({ params, searchParams }: PageProps<'/leads/[id]'>) {
  return (
    <Suspense fallback={<LeadSkeleton />}>
      <Lead params={params} searchParams={searchParams} />
    </Suspense>
  )
}

async function Lead({ params, searchParams }: Pick<PageProps<'/leads/[id]'>, 'params' | 'searchParams'>) {
  const [{ id }, sp] = await Promise.all([params, searchParams])
  if (!UUID.test(id)) notFound()
  // Unverified facts are an admin view: ask for them only when the link asks, and drop the request
  // below for anyone who is not an admin. Everything here runs as the user (RLS), so it starts now.
  const wantsUnverified = sp.unverified === '1'
  const detailP = early(getLeadDetail(id, { includeUnverified: wantsUnverified }))
  const verifiedOnlyP = wantsUnverified ? early(getLeadDetail(id, { includeUnverified: false })) : detailP
  const user = await requireUser()
  const isAdmin = canSeeMoney(user.role)
  const editable = canEdit(user.role)
  const includeUnverified = isAdmin && wantsUnverified
  const [detail, team, segments, proposals, dealValue] = await Promise.all([
    includeUnverified ? detailP : verifiedOnlyP,
    getTeam(),
    getSegments(),
    isAdmin ? getProposals(id) : Promise.resolve([]),
    isAdmin ? getLeadDealValue(id) : Promise.resolve(undefined),
  ])
  if (!detail) notFound()
  const { business, contacts, signals, facts, score, activities, feedback, pages } = detail
  const lead = { ...detail.lead, deal_value_inr: dealValue }
  const now = new Date()
  const names = new Map(team.map((m) => [m.id, m.name]))
  const segmentOf = segmentLabeler(segments)
  const blocked = new Set(detail.suppressedPhones)
  const website = safeUrl(business?.website ?? lead.website)
  const mapsUrl = business?.place_id ? `https://www.google.com/maps/place/?q=place_id:${encodeURIComponent(business.place_id)}` : null
  const needsEdit = activities.some((a) => a.type === 'message_flagged') && !activities.some((a) => a.type === 'message_edited')
  const myFeedback = feedback.find((f) => f.user_id === user.id) ?? null
  const primary = { phone: lead.phone_e164, phoneType: lead.phone_type, email: lead.email }

  const contactViews: ContactView[] = contacts.map((c) => ({
    id: c.id,
    name: c.name,
    role: c.role,
    phone: c.phone_e164,
    phoneDisplay: formatPhone(c.phone_e164),
    phoneType: c.phone_type,
    email: c.email,
    source: c.source,
    sourceUrl: safeUrl(c.source_url),
    isDecisionMaker: c.is_decision_maker,
    verified: c.verified,
    blocked: c.do_not_contact || (c.phone_e164 ? blocked.has(c.phone_e164) : false),
    blockReason: c.do_not_contact ? 'marked on the contact' : c.phone_e164 && blocked.has(c.phone_e164) ? 'on the list' : null,
  }))

  const factsToggle = isAdmin ? (
    <Link href={includeUnverified ? `/leads/${id}` : `/leads/${id}?unverified=1`} className="text-sm text-tx-3 hover:text-indigo-800" scroll={false}>
      {includeUnverified ? 'Verified only' : 'Show unverified'}
    </Link>
  ) : null

  return (
    <>
      <Link href="/leads" className="mb-4 inline-flex items-center gap-1.5 text-sm text-tx-3 hover:text-indigo-800">
        <ArrowLeft aria-hidden className="size-4" />
        Leads
      </Link>

      <header className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="font-display text-title font-normal text-balance text-tx-1">{lead.name}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 text-md text-tx-3">
              <span>{[lead.locality, lead.city, countryLabel(lead.country)].filter(Boolean).join(', ')}</span>
              {lead.segment_id ? <span className="label-mono">{segmentOf(lead.segment_id)}</span> : null}
              {website ? (
                <a href={website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-indigo-800 hover:text-indigo-900">
                  {hostOf(website)}
                  <ExternalLink aria-hidden className="size-3.5" />
                </a>
              ) : null}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <GradeBadge grade={lead.grade} className="size-8 text-base" />
            <div className="text-right">
              <div className="font-display text-[26px] leading-none text-indigo-900 tabular">
                {lead.total === null ? 'Not scored' : Math.round(Number(lead.total))}
                {lead.total === null ? null : <span className="text-md text-tx-3"> / 100</span>}
              </div>
              <div className="label-mono mt-1">Score</div>
            </div>
          </div>
        </div>

        <div data-tour="lead-controls" className="mt-5 flex flex-wrap items-end gap-3 rounded-2xl border border-line-2 bg-surface p-4">
          {editable ? (
            <>
              <StageSelect leadId={lead.id} stage={lead.stage} isAdmin={isAdmin} />
              {isAdmin ? <OwnerSelect leadId={lead.id} ownerId={lead.owner_id} team={team.map((m) => ({ id: m.id, name: m.name }))} /> : null}
              <NextStepEditor key={`${lead.next_step}-${lead.due_at}`} leadId={lead.id} nextStep={lead.next_step} dueAt={lead.due_at} />
            </>
          ) : (
            <div className="flex flex-wrap items-center gap-4 text-base">
              <StageBadge stage={lead.stage} />
              {lead.next_step ? <span className="text-tx-2">Next: {lead.next_step}</span> : null}
              {lead.due_at ? <span className="text-tx-3">Due {formatDate(lead.due_at, now)}</span> : null}
            </div>
          )}
          <dl className="ml-auto flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {lead.wa_at ? (
              <div>
                <dt className="label-mono">First message</dt>
                <dd className="text-tx-2">{formatDate(lead.wa_at, now)}</dd>
              </div>
            ) : null}
            {lead.created_at ? (
              <div>
                <dt className="label-mono">Added</dt>
                <dd className="text-tx-2">{formatDate(lead.created_at, now)}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-6 lg:order-2">
          <ContactCard leadId={lead.id} contacts={contactViews} message={lead.message} website={website} mapsUrl={mapsUrl} canEdit={editable} />
          {isAdmin ? (
            <DealCard leadId={lead.id} value={lead.deal_value_inr ?? null} country={lead.country} proposals={proposals.map((p) => ({ path: p.path, name: p.name, size: p.size }))} />
          ) : null}
          <FeedbackCard leadId={lead.id} mine={myFeedback ? { rating: myFeedback.rating, reason: myFeedback.reason } : null} />
          <NotesCard leadId={lead.id} summary={lead.notes} canEdit={editable} />
          <PagesCard pages={pages} now={now} />
        </div>
        <div className="flex min-w-0 flex-col gap-6 lg:order-1">
          <WhyCard score={score} pitchMode={lead.pitch_mode} testGroup={lead.test_group} judgeNote={lead.judge_note} />
          <MessageCard
            key={`${lead.message}|${lead.message_alt}`}
            leadId={lead.id}
            message={lead.message ?? ''}
            messageAlt={lead.message_alt ?? ''}
            regenRequestedAt={lead.regen_requested_at}
            needsEdit={needsEdit}
            target={primary}
            canEdit={editable}
          />
          <FollowupsCard
            key={`${lead.followup_d3}|${lead.followup_d7}`}
            leadId={lead.id}
            d3={lead.followup_d3 ?? ''}
            d7={lead.followup_d7 ?? ''}
            d3SentOn={lead.d3_at ? formatDate(lead.d3_at, now) : null}
            d7SentOn={lead.d7_at ? formatDate(lead.d7_at, now) : null}
            target={primary}
            canEdit={editable && Boolean(lead.wa_at)}
          />
          <SignalsCard signals={signals} now={now} />
          <FactsCard facts={facts} toggle={factsToggle} />
          <TechCard facts={facts} />
          <Timeline activities={activities} names={names} now={now} />
        </div>
      </div>
    </>
  )
}
