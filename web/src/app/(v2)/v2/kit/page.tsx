import type { Metadata } from 'next'
import { Page } from '@/components/ui2/large-title'
import { KitDemo } from './kit-demo'

export const metadata: Metadata = { title: 'Design kit' }

/**
 * The new design's building blocks in one place, for review and for whoever builds the next v2 page.
 * Only at /v2/kit (not on the v2 list, not in the navigation). Sample text only, never real leads.
 */
export default function KitPage() {
  return (
    <Page title="Design kit" subtitle="The building blocks of the new design, with sample text.">
      <KitDemo />
    </Page>
  )
}
