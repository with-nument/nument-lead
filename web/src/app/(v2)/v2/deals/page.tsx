import type { Metadata } from 'next'
import { Handshake } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Deals' }

export default function DealsPage() {
  return (
    <Placeholder title="Deals" icon={<Handshake />} heading="Deals will live here" classicHref="/pipeline" classicLabel="Open the Pipeline">
      Proposals and wins in one place. Until then, they are in the Pipeline.
    </Placeholder>
  )
}
