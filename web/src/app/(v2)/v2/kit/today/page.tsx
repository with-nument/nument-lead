import type { Metadata } from 'next'
import { TodayDate } from '@/components/shell2/today-date'
import { Page } from '@/components/ui2/large-title'
import { headline, type TodayData } from '../../_today/build'
import { CallsSection } from '../../_today/calls'
import { FollowupsSection } from '../../_today/followups'
import { OvernightCard } from '../../_today/overnight'
import { ProposalsSection } from '../../_today/proposals'
import { RepliesSection } from '../../_today/replies'
import { StartupsSection } from '../../_today/startups'

export const metadata: Metadata = { title: 'Today, sample' }

// Sample text only (the approved mockup's names), never real leads. For review and for the email lane, which
// feeds replies, calls and proposals into these same sections.
const SAMPLE: TodayData = {
  replies: [
    { id: 'r1', leadId: '00000000-0000-4000-8000-000000000001', person: 'Maya Rao', company: 'Leafline', quote: 'Yes, open to a call next week. Roughly what would a first version cost?', suggestion: 'offers Thu 6:30 pm or Fri 11 am and a ₹2–3L range' },
    { id: 'r2', leadId: '00000000-0000-4000-8000-000000000002', person: 'Ishaan Bose', company: 'Mosaic Tutors', quote: 'Not right now. Maybe after our round closes in March.', suggestion: 'thanks him and sets a reminder for 2 March' },
  ],
  calls: [
    { id: 'c1', leadId: '00000000-0000-4000-8000-000000000003', time: '6:30 pm', person: 'Arjun Mehta', company: 'Quill Legal', note: 'Brief ready · wants a contract review assistant' },
    { id: 'c2', leadId: '00000000-0000-4000-8000-000000000004', time: '8:00 pm', person: 'Sara Thomas', company: 'Kindred Pets', note: 'Brief ready · booking app for pet sitters' },
  ],
  proposals: [{ id: 'p1', leadId: '00000000-0000-4000-8000-000000000005', company: 'Orbit Kitchen', person: 'Rohan Iyer', note: 'Drafted from Friday’s call · kitchen ops app, 6 weeks · ₹2.4L' }],
  followups: [{ leadId: '00000000-0000-4000-8000-000000000006', company: 'Tessera Labs', person: 'Dev Malhotra', which: 'd3', note: 'Viewed the plan page 3 times, no reply in 5 days', overdue: false }],
  startups: ['Fieldnote', 'Sprout Finance', 'Lumen Dental', 'Northwind', 'Pebble', 'Arcadia', 'Brightpath', 'Cobalt'].map((company, i) => ({
    leadId: `00000000-0000-4000-8000-0000000001${String(i).padStart(2, '0')}`,
    company,
    grade: i % 3 ? 'B' : 'A',
    city: 'Bengaluru',
    person: null,
    signal: 'Hiring a first engineer',
  })),
}

/** The Today page with sample data in every section (/v2/kit/today). Buttons that save are off (view only). */
export default function KitTodayPage() {
  // A fixed morning, so the sample prerenders and reads like the mockup.
  const head = headline(SAMPLE, new Date('2026-11-16T03:30:00Z'))
  return (
    <Page title={head.title} compactTitle={head.compact} eyebrow={<TodayDate />} subtitle={head.subtitle}>
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-8">
        <div>
          <RepliesSection step={1} items={SAMPLE.replies} primary canEdit={false} />
          <CallsSection step={2} items={SAMPLE.calls} />
          <ProposalsSection step={3} items={SAMPLE.proposals} />
          <FollowupsSection step={4} items={SAMPLE.followups} canEdit={false} />
          <StartupsSection step={5} items={SAMPLE.startups} canEdit={false} summary="All grade A or B · emails verified · 12-day sequence ready" />
        </div>
        <OvernightCard
          title="Overnight"
          window="1:00 – 4:12 am"
          rows={[
            { label: 'Startups found', value: '42' },
            { label: 'Passed every check', value: '17' },
            { label: 'Emails sent', value: '64' },
            { label: 'Replies', value: '4' },
            { label: 'Plan pages viewed', value: '6' },
          ]}
          health={{ tone: 'ok', text: 'Sending is healthy · 0.4% bounced' }}
          link={{ href: '/insights', label: 'See Insights' }}
        />
      </div>
    </Page>
  )
}
