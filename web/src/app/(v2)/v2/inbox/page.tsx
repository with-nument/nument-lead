import type { Metadata } from 'next'
import { Inbox } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'

export const metadata: Metadata = { title: 'Inbox' }

// Not on the v2 list yet (src/lib/ui-flag.ts): /inbox still opens the current design.
export default function InboxPage() {
  return (
    <Placeholder title="Inbox" icon={<Inbox />} heading="Inbox is being redesigned">
      Until it is ready, it opens in the classic design.
    </Placeholder>
  )
}
