import type { Metadata } from 'next'
import { Phone } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Calls' }

export default function CallsPage() {
  return (
    <Placeholder title="Calls" icon={<Phone />} heading="Calls will live here" classicHref="/pipeline" classicLabel="Open the Pipeline">
      Every booked call, with who to call and when. Until then, booked calls are in the Pipeline.
    </Placeholder>
  )
}
