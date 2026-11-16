import type { Metadata } from 'next'
import Link from 'next/link'
import { Suspense } from 'react'
import { Column, Columns, Meter, Panel, Row, Section, StatusDot } from '@/app/(v2)/v2/_parts/section'
import { Page } from '@/components/ui2/large-title'
import { Skeleton } from '@/components/ui2/skeleton'
import { early, requireRole } from '@/lib/auth'
import { formatDateTime, relativeAge } from '@/lib/dates'
import { formatInr, formatNumber, hostOf, safeUrl } from '@/lib/format'
import { isDispatchConfigured } from '@/lib/github'
import { getEngineLive, getEngineOverview } from '@/lib/queries/engine'
import { getInboxPosts } from '@/lib/queries/inbox'
import { segmentLabeler } from '@/lib/queries/shared'
import { AddPostButton, AddQueryButton, BudgetEditButton, QuotaInput, RunNowButton, SegmentSwitch, SourceSwitch } from './_parts/controls'
import { POST_STATUS, QUERY_STATUS, RUN_LABEL, runDuration, runResult, runStatus, sourceHealth } from './labels'

export const metadata: Metadata = { title: 'Engine' }

const SUBTITLE = 'How the engine finds leads: runs, sources, spend and the posts you paste.'

export default function EnginePage() {
  return (
    <Suspense fallback={<EngineSkeleton />}>
      <Engine />
    </Suspense>
  )
}

async function Engine() {
  // The live reads run as the user (Row Level Security: admins only) and start while the role is checked.
  const live = early(getEngineLive())
  const posts = early(getInboxPosts())
  await requireRole(['admin'])
  const [data, inbox] = await Promise.all([getEngineOverview(live), posts])
  const now = new Date()
  const segments = data.segments
  const options = segments.map((s) => ({ id: s.id, label: s.label }))
  const segmentOf = segmentLabeler(segments)
  const cap = data.budget.daily_cap_inr
  const nearCap = cap > 0 && data.spendToday >= (cap * data.budget.alert_pct) / 100
  const last = data.runs[0]

  return (
    <Page title="Engine" subtitle={SUBTITLE} actions={<RunNowButton segments={options} configured={isDispatchConfigured()} />}>
      <Columns>
        <Column>
          <Section id="runs-title" title="Runs" description={last ? `Last: ${RUN_LABEL[last.kind] ?? last.kind}, ${relativeAge(last.started_at, now)}.` : 'Nothing has run yet.'}>
            <Panel>
              {data.runs.length ? (
                data.runs.slice(0, 10).map((r) => {
                  const st = runStatus(r.status)
                  const took = runDuration(r.started_at, r.finished_at)
                  return (
                    <Row key={r.id} trailing={<StatusDot tone={st.tone}>{st.label}</StatusDot>}>
                      <p className="truncate font-medium">{RUN_LABEL[r.kind] ?? r.kind}</p>
                      <p className="type-caption truncate text-label-3" title={r.error ?? undefined}>
                        {[formatDateTime(r.started_at), took, r.error ? r.error : runResult(r.stats, formatInr)].filter(Boolean).join(' · ')}
                      </p>
                    </Row>
                  )
                })
              ) : (
                <Row>
                  <span className="block text-label-3">The first night run will show here.</span>
                </Row>
              )}
            </Panel>
          </Section>

          <Section id="segments-title" title="Segments" description="Daily quota is how many businesses the engine researches per day in each.">
            <Panel>
              {segments.length ? (
                segments.map((s) => (
                  <Row
                    key={s.id}
                    trailing={
                      <>
                        <QuotaInput id={s.id} label={s.label} quota={s.daily_quota} />
                        <SegmentSwitch id={s.id} label={s.label} enabled={s.enabled} />
                      </>
                    }
                  >
                    <p className={s.enabled ? 'truncate' : 'truncate text-label-3'}>{s.label}</p>
                    <p className="type-caption truncate text-label-3 tabular-nums">
                      Yesterday: {formatNumber(s.researchedYesterday)} researched · {formatNumber(s.leadsYesterday)} {s.leadsYesterday === 1 ? 'lead' : 'leads'}
                    </p>
                  </Row>
                ))
              ) : (
                <Row>
                  <span className="block text-label-3">No segments yet. They come from the engine&apos;s config.</span>
                </Row>
              )}
            </Panel>
          </Section>

          <Section id="posts-title" title="Posts" description="Public posts you paste, where someone asks for help. The engine never opens LinkedIn or X." action={<AddPostButton segments={options} />}>
            <Panel>
              {inbox.length ? (
                inbox.slice(0, 8).map((p) => {
                  const url = safeUrl(p.url)
                  return (
                    <Row
                      key={p.id}
                      trailing={
                        p.lead_id ? (
                          <Link href={`/leads/${p.lead_id}`} className="type-subhead font-medium text-label-1 underline decoration-separator-strong underline-offset-4 lg:text-[13.5px]">
                            Open lead
                          </Link>
                        ) : undefined
                      }
                    >
                      <p className="line-clamp-2 whitespace-pre-line">{p.text}</p>
                      <p className="type-caption mt-0.5 truncate text-label-3">
                        {[POST_STATUS[p.status] ?? p.status, p.segment_id ? segmentOf(p.segment_id) : '', url ? hostOf(url) : '', relativeAge(p.created_at, now)].filter(Boolean).join(' · ')}
                      </p>
                    </Row>
                  )
                })
              ) : (
                <Row>
                  <span className="block text-label-3">No posts yet. Paste one when you see someone asking for an app, a website or automation.</span>
                </Row>
              )}
            </Panel>
          </Section>
        </Column>

        <Column>
          <Section id="budget-title" title="Budget" description="Spend today, against the daily cap." action={<BudgetEditButton budget={data.budget} />}>
            <Panel>
              <div className="px-4 py-4 lg:px-5 lg:py-[18px]">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[15px] lg:text-[14.5px]">
                  <span className="font-medium text-label-1 tabular-nums">{formatInr(data.spendToday) || '₹0'} today</span>
                  <span className="text-label-3 tabular-nums">of {formatInr(cap)}</span>
                </div>
                <Meter className="mt-2.5" label="Spend today" value={data.spendToday} max={cap} tone={nearCap ? 'bad' : 'ink'} />
              </div>
              <Row label="Alert at">
                <span className="tabular-nums">{data.budget.alert_pct}% of the cap</span>
              </Row>
              <Row label="Research">
                <span className="tabular-nums">{formatNumber(data.budget.research_per_day)} businesses a day</span>
              </Row>
            </Panel>
          </Section>

          <Section id="sources-title" title="Sources" description="Turn one off to stop the engine using it at once.">
            <Panel>
              {data.sources.length ? (
                data.sources.map((s) => {
                  const h = sourceHealth(s.health)
                  const blocked = s.blocked_until && Date.parse(s.blocked_until) > now.getTime()
                  const detail = [
                    s.last_ok_at ? `Worked ${relativeAge(s.last_ok_at, now)}` : 'Never worked yet',
                    `${formatNumber(s.requests_today ?? 0)} today`,
                    blocked ? `Blocked until ${formatDateTime(s.blocked_until!)}` : '',
                  ].filter(Boolean)
                  return (
                    <Row key={s.source} trailing={<SourceSwitch source={s.source} enabled={Boolean(s.enabled)} />}>
                      <div className="flex min-w-0 items-center gap-3">
                        <p className="min-w-0 flex-1 truncate">{s.source}</p>
                        <span className="type-caption shrink-0 text-label-2">
                          <StatusDot tone={h.tone}>{h.label}</StatusDot>
                        </span>
                      </div>
                      <p className="type-caption truncate text-label-3" title={s.last_error ?? undefined}>
                        {(h.tone === 'bad' && s.last_error ? [s.last_error, ...detail.slice(1)] : detail).join(' · ')}
                      </p>
                    </Row>
                  )
                })
              ) : (
                <Row>
                  <span className="block text-label-3">No sources registered yet. The first run registers them.</span>
                </Row>
              )}
            </Panel>
          </Section>

          <Section id="queries-title" title="Search queue" description="Ask the night run to look for something specific." action={<AddQueryButton segments={options} />}>
            <Panel>
              {data.queries.length ? (
                data.queries.slice(0, 8).map((q) => (
                  <Row key={q.id} trailing={<span className="type-caption text-label-3">{QUERY_STATUS[q.status] ?? q.status}</span>}>
                    <p className="truncate">{q.query}</p>
                    <p className="type-caption truncate text-label-3">
                      {segmentOf(q.segment_id)} · {relativeAge(q.created_at, now)}
                    </p>
                  </Row>
                ))
              ) : (
                <Row>
                  <span className="block text-label-3">Nothing queued.</span>
                </Row>
              )}
            </Panel>
          </Section>
        </Column>
      </Columns>
    </Page>
  )
}

/** Same frame as the page: the title, then two columns of panels. */
function EngineSkeleton() {
  const block = (rows: number) => (
    <div className="flex flex-col">
      <Skeleton className="mb-3 ml-1 h-4 w-24" />
      <div role="presentation" className="material-panel overflow-hidden rounded-[20px] [&>*+*]:hairline-t">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex min-h-14 flex-col justify-center gap-2 px-4 lg:px-5">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
        ))}
      </div>
    </div>
  )
  return (
    <Page title="Engine" subtitle={SUBTITLE}>
      <div role="status" aria-label="Loading the engine" className="grid items-start gap-7 lg:grid-cols-2">
        <div className="flex flex-col gap-7">
          {block(6)}
          {block(4)}
        </div>
        <div className="flex flex-col gap-7">
          {block(3)}
          {block(5)}
        </div>
      </div>
    </Page>
  )
}
