'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/** Re-renders the page from the server every `seconds` while the tab is visible, and on focus (plan 15.5.5). */
export function AutoRefresh({ seconds = 60 }: { seconds?: number }) {
  const router = useRouter()
  useEffect(() => {
    let last = Date.now()
    const refresh = () => {
      if (document.visibilityState !== 'visible') return
      last = Date.now()
      router.refresh()
    }
    const timer = window.setInterval(refresh, seconds * 1000)
    const onFocus = () => {
      if (Date.now() - last > 10_000) refresh()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [router, seconds])
  return null
}
