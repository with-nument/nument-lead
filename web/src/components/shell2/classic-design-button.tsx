'use client'

import { Button } from '@/components/ui2/button'
import { switchDesign } from '@/lib/ui-flag'

/** Turns the new design off for this browser and reloads into the classic design. */
export function ClassicDesignButton({ label = 'Open the classic design' }: { label?: string }) {
  return (
    <Button variant="secondary" onClick={() => switchDesign(false)}>
      {label}
    </Button>
  )
}
