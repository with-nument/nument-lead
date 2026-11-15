import type { Metadata } from 'next'
import { UsersRound } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Leads' }

// Not on the v2 list yet (src/lib/ui-flag.ts): /leads still opens the current design.
export default function LeadsPage() {
  return (
    <Placeholder title="Leads" icon={<UsersRound />} heading="Leads is being redesigned" classicHref="/leads" classicLabel="Open Leads">
      Until it is ready, every lead is in the classic design.
    </Placeholder>
  )
}
