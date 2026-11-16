'use client'

import { Switch } from '@/app/(v2)/v2/_parts/switch'
import { switchDesign } from '@/lib/ui-flag'

/** The new design is on here by definition; switching it off reloads into the classic design. */
export function DesignSwitch() {
  return <Switch label="Use the new design" checked onCheckedChange={(v) => switchDesign(v)} />
}
