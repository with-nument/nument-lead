'use client'

import { useState } from 'react'
import { useRun } from '@/app/(v2)/v2/_parts/run'
import { Switch } from '@/app/(v2)/v2/_parts/switch'
import { setOutreachPaused } from '../actions'

/** Pause all sending: flips at once, rolls back if the save fails. */
export function PauseSwitch({ paused }: { paused: boolean }) {
  const [on, setOn] = useState(paused)
  const [pending, run] = useRun()
  return (
    <Switch
      label="Pause all sending"
      checked={on}
      disabled={pending}
      onCheckedChange={(v) => {
        setOn(v)
        run(() => setOutreachPaused({ paused: v }), { onFail: () => setOn(!v) })
      }}
    />
  )
}
