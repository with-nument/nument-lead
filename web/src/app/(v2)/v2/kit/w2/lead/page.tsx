import { LeadScreen } from '../../../leads/[id]/_lead/lead-screen'
import { leadExtras, leadView, previewOnly, team } from '../fixtures'

/** Preview: the lead page with an email thread and a reply waiting (sample data). */
export default function LeadPreview() {
  previewOnly()
  return <LeadScreen view={leadView()} canEdit isAdmin includeUnverified={false} team={team} proposals={[]} myFeedback={null} extras={leadExtras} initialTab="why" />
}
