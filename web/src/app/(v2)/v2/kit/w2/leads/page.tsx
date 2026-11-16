import { EMPTY_FILTERS } from '@/lib/leads-filters'
import { LeadsList } from '@/app/(v2)/v2/leads/_list/leads-list'
import { leadsProps, previewOnly } from '../fixtures'
import { MOCK_NOW } from '../mock'

/** Preview: the Leads list (sample data). */
export default function LeadsPreview() {
  previewOnly()
  return <LeadsList {...leadsProps()} filters={EMPTY_FILTERS} canEdit isAdmin canExport now={MOCK_NOW.toISOString()} />
}
