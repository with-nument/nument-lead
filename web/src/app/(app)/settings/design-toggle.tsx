'use client'

import { useState } from 'react'
import { Switch } from '@/components/ui/switch'
import { switchDesign } from '@/lib/ui-flag'

/** "Try the new design": sets or clears the nl_ui cookie for this browser, then reloads into it. */
export function DesignToggle({ on }: { on: boolean }) {
  const [checked, setChecked] = useState(on)
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-base font-medium text-tx-1">Try the new design</p>
        <p className="mt-0.5 text-sm text-tx-3">A calmer look that works the same on phone and laptop. Pages not redesigned yet open as they are now.</p>
      </div>
      <Switch
        label="Try the new design"
        checked={checked}
        onCheckedChange={(v) => {
          setChecked(v)
          switchDesign(v)
        }}
      />
    </div>
  )
}
