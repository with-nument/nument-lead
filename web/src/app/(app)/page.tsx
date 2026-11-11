import type { Metadata } from 'next'
import { Suspense } from 'react'
import { AutoRefresh } from '@/components/shell/auto-refresh'
import { Card, CardHeader } from '@/components/ui/card'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton, SkeletonRows } from '@/components/ui/skeleton'
import { FollowupList, type FollowupItem } from '@/components/today/followup-list'
import { SendList, type SendItem } from '@/components/today/send-list'
import { TodayKpiTiles } from '@/components/today/today-kpis'
import { requireUser } from '@/lib/auth'
import { dueState, formatDate, formatWeekday, istDate, relativeAge } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { formatPhone } from '@/lib/phone'
import { canEdit, canSeeMoney } from '@/lib/roles'
import { CONTACT_SOURCE_LABEL, PHONE_TYPE_LABEL, signalLabel } from '@/lib/signals'
import { getSegments, segmentLabeler } from '@/lib/queries/shared'
import { getFollowupsDue, getSendList, getTodayKpis, TODAY_LIMIT } from '@/lib/queries/today'

export const metadata: Metadata = { title: 'Today' }

export default function TodayPage() {
  return (
    <Suspense fallback={<TodaySkeleton />}>
      <Today />
    </Suspense>
  )
}

async function Today() {
  const user = await requireUser()
  const [kpis, sendRows, followups, segments] = await Promise.all([
    getTodayKpis(canSeeMoney(user.role)),
    getSendList(),
    getFollowupsDue(),
    getSegments(),
  ])
  const now = new Date()
  const today = istDate(now)
  const segmentOf = segmentLabeler(segments)
  const editable = canEdit(user.role)

  const items: SendItem[] = sendRows.map((r) => ({
    id: r.lead_id,
    name: r.business_name,
    city: r.city,
    segment: segmentOf(r.segment_id),
    grade: r.grade,
    signal: r.signal
      ? { label: signalLabel(r.signal.type), age: relativeAge(r.signal.observed_at, now), url: r.signal.url, quote: r.signal.quote }
      : null,
    contactName: r.contact_name,
    contactRole: r.contact_role,
    phone: r.phone_e164,
    phoneDisplay: formatPhone(r.phone_e164),
    phoneType: r.phone_type,
    phoneMeta: r.phone_e164
      ? [PHONE_TYPE_LABEL[r.phone_type ?? 'unknown'], CONTACT_SOURCE_LABEL[r.contact_source ?? 'other']].filter(Boolean).join(' · ')
      : '',
    email: r.email,
    message: r.message,
  }))

  const followupItems: FollowupItem[] = followups.map((f) => {
    const state = dueState(f.due_at, today)
    const followup =
      f.wa_at && !f.d3_at && f.followup_d3
        ? { which: 'd3' as const, text: f.followup_d3 }
        : f.wa_at && !f.d7_at && f.followup_d7
          ? { which: 'd7' as const, text: f.followup_d7 }
          : null
    return {
      id: f.lead_id,
      name: f.business_name,
      city: f.city,
      stage: f.stage,
      nextStep: f.next_step,
      dueLabel: state === 'today' ? 'today' : formatDate(f.due_at, now),
      overdue: state === 'overdue',
      phone: f.phone_e164,
      phoneType: f.phone_type,
      followup,
    }
  })

  return (
    <>
      <AutoRefresh seconds={60} />
      <PageHeader title="Today" actions={<span className="text-md text-tx-3">{formatWeekday(now)}</span>} />
      <TodayKpiTiles kpis={kpis} />

      <Card className="mt-6" aria-labelledby="send-list-title">
        <CardHeader
          id="send-list-title"
          title={`Send list · ${formatNumber(items.length)}${items.length >= TODAY_LIMIT ? '+' : ''}`}
          description="New A and B leads, best first. Opening WhatsApp marks the lead as contacted."
        />
        <div className="mt-2 border-t border-line-2">
          <SendList items={items} canEdit={editable} />
        </div>
      </Card>

      <Card className="mt-6" aria-labelledby="followups-title">
        <CardHeader id="followups-title" title={`Follow-ups due · ${formatNumber(followupItems.length)}`} description="Open leads whose next step is due today or earlier." />
        <div className="mt-2 border-t border-line-2">
          <FollowupList items={followupItems} canEdit={editable} />
        </div>
      </Card>
    </>
  )
}

function TodaySkeleton() {
  return (
    <div aria-busy>
      <PageHeader title="Today" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="rounded-xl border border-line-2 bg-surface px-4 py-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-12" />
          </div>
        ))}
      </div>
      <Card className="mt-6">
        <CardHeader title="Send list" />
        <div className="mt-2 border-t border-line-2">
          <SkeletonRows rows={4} />
        </div>
      </Card>
    </div>
  )
}
