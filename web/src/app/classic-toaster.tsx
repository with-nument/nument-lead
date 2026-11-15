'use client'

import { lazy, Suspense } from 'react'
import { useInV2 } from '@/components/ui2/scope'

// sonner, fetched after the page is interactive and only for current-design pages. The sign-in page
// and new-design pages (which have their own small toast) never download it. Toasts shown before it
// arrives still appear: sonner replays them to a Toaster that mounts later. React.lazy rather than
// next/dynamic, whose loader would add about 5 KB to every page, the sign-in page included.
const Sonner = lazy(() => import('sonner').then((m) => ({ default: m.Toaster })))

export function ClassicToaster() {
  // True on the server and during hydration, so this never renders (or fetches) before the page is live.
  const inV2 = useInV2()
  if (inV2) return null
  return (
    <Suspense fallback={null}>
      <Sonner position="bottom-right" closeButton duration={5000} />
    </Suspense>
  )
}
