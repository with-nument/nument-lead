import type { Metadata } from 'next'
import Link from 'next/link'
import { Suspense } from 'react'
import { InboxForm } from '@/components/engine/inbox-form'
import { Tag, type Tone } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import { SkeletonRows } from '@/components/ui/skeleton'
import { early, requireRole } from '@/lib/auth'
import { relativeAge } from '@/lib/dates'
import { hostOf, safeUrl } from '@/lib/format'
import { getInboxPosts } from '@/lib/queries/inbox'
import { getSegments, segmentLabeler } from '@/lib/queries/shared'

export const metadata: Metadata = { title: 'Inbox' }

const STATUS_TONE: Record<string, Tone> = { new: 'neutral', processing: 'indigo', processed: 'indigo', researched: 'indigo', lead_created: 'ok', rejected: 'bad' }
const STATUS_LABEL: Record<string, string> = { new: 'New', processing: 'Processing', processed: 'Processed', researched: 'Researched', lead_created: 'Lead created', rejected: 'Rejected' }

export default function InboxPage() {
  return (
    <>
      <PageHeader title="Inbox" description="Paste public posts where someone asks for help. The engine works from the text you paste and never opens LinkedIn or X." />
      <Suspense
        fallback={
          <Card>
            <SkeletonRows rows={4} />
          </Card>
        }
      >
        <Inbox />
      </Suspense>
    </>
  )
}

async function Inbox() {
  // Posts run as the user (RLS: admin only) and start while the role is checked.
  const postsP = early(getInboxPosts())
  await requireRole(['admin'])
  const [posts, segments] = await Promise.all([postsP, getSegments()])
  const segmentOf = segmentLabeler(segments)
  const now = new Date()
  return (
    <div className="flex flex-col gap-6">
      <Card aria-labelledby="paste-title" data-tour="inbox-paste">
        <CardHeader id="paste-title" title="Add a post" />
        <CardBody>
          <InboxForm segments={segments.map((s) => ({ id: s.id, label: s.label }))} />
        </CardBody>
      </Card>
      <Card aria-labelledby="posts-title">
        <CardHeader id="posts-title" title={`Posts · ${posts.length}`} />
        <div className="mt-3 border-t border-line-2">
          {posts.length ? (
            <ul className="divide-y divide-line-2">
              {posts.map((p) => {
                const url = safeUrl(p.url)
                return (
                  <li key={p.id} className="px-4 py-3 sm:px-5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Tag tone={STATUS_TONE[p.status] ?? 'neutral'}>{STATUS_LABEL[p.status] ?? p.status}</Tag>
                      {p.segment_id ? <span className="label-mono">{segmentOf(p.segment_id)}</span> : null}
                      <span className="text-xs text-tx-3">{relativeAge(p.created_at, now)}</span>
                      {url ? (
                        <a href={url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-800 hover:text-indigo-900">
                          {hostOf(url)}
                        </a>
                      ) : null}
                      {p.lead_id ? (
                        <Link href={`/leads/${p.lead_id}`} className="ml-auto text-sm text-indigo-800 hover:text-indigo-900">
                          Open lead
                        </Link>
                      ) : null}
                    </div>
                    <p className="mt-1.5 line-clamp-3 text-base whitespace-pre-line text-tx-2">{p.text}</p>
                  </li>
                )
              })}
            </ul>
          ) : (
            <EmptyState text="No posts yet. Paste one above when you see someone asking for help." />
          )}
        </div>
      </Card>
    </div>
  )
}
