import { LeadScreen } from '@/app/(v2)/v2/leads/[id]/_lead/lead-screen'
import { leadView, previewOnly, team } from '../fixtures'

/** Preview: the lead page before any email thread exists (sample data). */
export default function LeadPlainPreview() {
  previewOnly()
  return <LeadScreen view={leadView()} canEdit isAdmin includeUnverified={false} team={team} proposals={[]} myFeedback={null} initialTab="conversation" />
}
