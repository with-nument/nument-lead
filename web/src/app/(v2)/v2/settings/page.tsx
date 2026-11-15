import type { Metadata } from 'next'
import { Settings } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Settings' }

// Not on the v2 list yet (src/lib/ui-flag.ts): /settings still opens the current design.
export default function SettingsPage() {
  return (
    <Placeholder title="Settings" icon={<Settings />} heading="Settings is being redesigned" classicHref="/settings" classicLabel="Open Settings">
      Until it is ready, your profile, password and the design switch are in the classic design.
    </Placeholder>
  )
}
