'use client'

import Link from 'next/link'
import { useEffect, useRef, useState, type ComponentProps, type FocusEvent, type MouseEvent, type TouchEvent } from 'react'

const COOL_MS = 10_000

type Props = ComponentProps<typeof Link> & {
  /** How long the pointer must rest on the link before its data is fetched (0: at once). Lists use a short wait, so sweeping the mouse over them fetches nothing. */
  dwellMs?: number
  /** False: no prefetch at all until the intent (long lists, where prefetching every visible row costs more than it saves). */
  viewport?: boolean
}

/**
 * A link that fetches the whole next page (its data too) as soon as someone shows the intent to open it:
 * hover, touch or keyboard focus. Until then it prefetches only the page's prerendered shell when it scrolls
 * into view, like any link. With the data already here, the click shows the finished page at once instead of
 * its skeleton. Next.js keeps a prefetched page for 30 s (`staleTimes.static` in next.config.ts), and a Server
 * Action that changes data clears it.
 */
export function IntentLink({ dwellMs = 0, viewport = true, onMouseEnter, onMouseLeave, onTouchStart, onFocus, onBlur, prefetch, ...props }: Props) {
  const [hot, setHot] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  // Back to a shell-only prefetch after a while: the fetched page stays in the router cache, and a link left in
  // full mode would fetch the data again each time the cache is cleared.
  useEffect(() => {
    if (!hot) return
    const cool = window.setTimeout(() => setHot(false), COOL_MS)
    return () => window.clearTimeout(cool)
  }, [hot])
  const warm = () => {
    if (hot || prefetch === false) return
    window.clearTimeout(timer.current)
    if (dwellMs > 0) timer.current = window.setTimeout(() => setHot(true), dwellMs)
    else setHot(true)
  }
  return (
    <Link
      {...props}
      prefetch={hot ? true : viewport ? prefetch : false}
      onMouseEnter={(e: MouseEvent<HTMLAnchorElement>) => {
        onMouseEnter?.(e)
        warm()
      }}
      onMouseLeave={(e: MouseEvent<HTMLAnchorElement>) => {
        onMouseLeave?.(e)
        window.clearTimeout(timer.current)
      }}
      onTouchStart={(e: TouchEvent<HTMLAnchorElement>) => {
        onTouchStart?.(e)
        if (!hot && prefetch !== false) setHot(true)
      }}
      onFocus={(e: FocusEvent<HTMLAnchorElement>) => {
        onFocus?.(e)
        warm()
      }}
      onBlur={(e: FocusEvent<HTMLAnchorElement>) => {
        onBlur?.(e)
        window.clearTimeout(timer.current)
      }}
    />
  )
}
