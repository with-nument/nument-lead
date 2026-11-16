// Server-side helpers for the W2 preview pages: sample data turned into the screens' props.
import { notFound } from 'next/navigation'
import { toBoardView } from '../../deals/_board/model'
import { toLeadView } from '../../leads/[id]/_lead/model'
import type { LeadExtras } from '../../leads/[id]/_lead/types'
import { toRow } from '../../leads/_list/model'
import { MOCK_LEAD_ID, MOCK_NOW, mockBoard, mockLeadDetail, mockLeadRows } from './mock'

/** Previews exist for design review and screenshots only; production answers 404. */
export function previewOnly() {
  if (process.env.NODE_ENV === 'production' && process.env.APP_ENV !== 'preview') notFound()
}

export const team = [{ id: '00000000-0000-4000-8000-000000000900', name: 'Team Nument' }]

export const leadView = () => toLeadView(mockLeadDetail, { now: MOCK_NOW, isAdmin: true, names: new Map(), segmentOf: () => 'Startups' })

export const leadExtras: LeadExtras = {
  thread: {
    id: '00000000-0000-4000-8000-000000000700',
    toEmail: 'maya@leafline.example',
    status: 'open',
    stopReason: null,
    pausedUntil: null,
    suggestedReply: {
      messageId: '00000000-0000-4000-8000-000000000705',
      body: 'Hi Maya, glad it landed. Thursday at 4 pm or Friday at 11 am both work for a 20 minute call. I will bring a rough plan for the ordering app so we can talk numbers.',
    },
    messages: [
      { id: '00000000-0000-4000-8000-000000000701', direction: 'out', step: 0, subject: 'Orders on WhatsApp', body: 'Hi Maya, saw the year-one post about orders typed into a sheet by hand...', status: 'sent', at: '2026-11-02T05:00:00Z' },
      { id: '00000000-0000-4000-8000-000000000702', direction: 'out', step: 3, subject: null, body: 'One more thought: we could start with just repeat orders.', status: 'sent', at: '2026-11-05T05:00:00Z' },
      { id: '00000000-0000-4000-8000-000000000703', direction: 'out', step: 7, subject: null, body: 'Closing the loop here.', status: 'sent', at: '2026-11-10T05:00:00Z' },
      { id: '00000000-0000-4000-8000-000000000704', direction: 'in', step: null, subject: null, body: 'Hi! Yes, this is exactly where we are stuck. Could we talk this week?', status: 'received', at: '2026-11-16T03:30:00Z', from: 'Maya' },
      { id: '00000000-0000-4000-8000-000000000706', direction: 'out', step: 12, subject: null, body: null, status: 'cancelled', at: null },
    ],
  },
  planPage: { views: 3, lastViewedAt: '2026-11-15T16:10:00Z', url: null, note: 'Spent most time on pricing' },
}

export const leadsProps = () => ({
  rows: mockLeadRows.map((r) => toRow(r, () => 'Startups', MOCK_NOW)),
  total: 1284,
  pageSize: 50,
  newCount: 42,
  options: { segments: [{ id: 'startups-in', label: 'Startups' }], countries: ['in'], cities: ['Bengaluru', 'Delhi', 'Pune'], team, showOwner: true },
  views: { mine: [], shared: [] },
})

export const boardView = () => toBoardView(mockBoard, { now: MOCK_NOW, isAdmin: true })
export { MOCK_LEAD_ID }
