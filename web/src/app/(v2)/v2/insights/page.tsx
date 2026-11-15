import type { Metadata } from 'next'
import { ChartColumn } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Insights' }

// Not on the v2 list yet (src/lib/ui-flag.ts): /insights still opens the current design.
export default function InsightsPage() {
  return (
    <Placeholder title="Insights" icon={<ChartColumn />} heading="Insights is being redesigned" classicHref="/insights" classicLabel="Open Insights">
      Until it is ready, the numbers are in the classic design.
    </Placeholder>
  )
}
