'use client'

import { useSyncExternalStore } from 'react'

const fmt = new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })
const noop = () => () => {}

/** Today's date in India time, filled in by the browser so the page shell stays prerendered. */
export function TodayDate() {
  const text = useSyncExternalStore(
    noop,
    () => fmt.format(new Date()),
    () => '',
  )
  return <span suppressHydrationWarning>{text || ' '}</span>
}
