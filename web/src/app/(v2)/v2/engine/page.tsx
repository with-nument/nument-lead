import type { Metadata } from 'next'
import { Cpu } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Engine' }

// Not on the v2 list yet (src/lib/ui-flag.ts): /engine still opens the current design.
export default function EnginePage() {
  return (
    <Placeholder title="Engine" icon={<Cpu />} heading="Engine is being redesigned" classicHref="/engine" classicLabel="Open Engine">
      Until it is ready, runs and settings are in the classic design.
    </Placeholder>
  )
}
