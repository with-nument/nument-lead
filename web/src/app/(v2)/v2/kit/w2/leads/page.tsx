import { EMPTY_FILTERS } from '@/lib/leads-filters'
import { LeadsList } from '../../../leads/_list/leads-list'
import { leadsProps, previewOnly } from '../fixtures'

/** Preview: the Leads list (sample data). */
export default function LeadsPreview() {
  previewOnly()
  return <LeadsList {...leadsProps()} filters={EMPTY_FILTERS} canEdit isAdmin canExport />
}
