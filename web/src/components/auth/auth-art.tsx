'use client'

import { lazy, Suspense, useEffect, useState } from 'react'
import { cx } from '@/components/ui2/cx'

// three.js is about 150 KB gzipped, so it never joins the sign-in page's first load: the poster (a
// still of the scene) paints with the page, the scene's code is fetched once the page is idle, and the
// live canvas fades in over the poster when its first frame is drawn. No WebGL: the poster stays.
// React.lazy rather than next/dynamic: it is only ever rendered in the browser (after an effect), so
// ssr:false is implied, and next/dynamic's loader would add 2.3 KB to the page's first load, past
// its 140 KB budget.
const CoinsScene = lazy(() => import('./coins-scene'))

/** Waits for the first paint and an idle moment before the scene starts loading. */
function useAfterFirstPaint() {
  const [ok, setOk] = useState(false)
  useEffect(() => {
    let idle = 0
    let timer = 0
    const raf = requestAnimationFrame(() => {
      if (typeof requestIdleCallback === 'function') idle = requestIdleCallback(() => setOk(true), { timeout: 1200 })
      else timer = window.setTimeout(() => setOk(true), 150)
    })
    return () => {
      cancelAnimationFrame(raf)
      if (idle) cancelIdleCallback(idle)
      clearTimeout(timer)
    }
  }, [])
  return ok
}

const fade = 'transition-opacity duration-700 ease-[cubic-bezier(0.25,1,0.5,1)]'

/** The art panel: poster first, then the interactive coins. Decorative, so hidden from assistive tech. */
export function AuthArt() {
  const load = useAfterFirstPaint()
  const [live, setLive] = useState(false)
  return (
    <div aria-hidden className="absolute inset-0 overflow-hidden">
      {/* The poster keeps the scene's framing: full height, centred, like the camera's fixed vertical view.
          It is a 4:3 render, wide enough to cover the panel on desktop and phones without showing its edges. */}
      <picture>
        <source
          type="image/webp"
          srcSet="/auth/scene-poster-1200.webp 1200w, /auth/scene-poster-2400.webp 2400w"
          sizes="(max-width: 900px) 62vh, 134vh"
        />
        <img
          src="/auth/scene-poster.png"
          alt=""
          width={1200}
          height={900}
          fetchPriority="high"
          draggable={false}
          className={cx('pointer-events-none absolute top-0 left-1/2 h-full w-auto max-w-none -translate-x-1/2 select-none', fade, live && 'opacity-0')}
        />
      </picture>
      {load ? (
        <Suspense>
          <CoinsScene onReady={() => setLive(true)} onLost={() => setLive(false)} className={cx('absolute inset-0', fade, !live && 'opacity-0')} />
        </Suspense>
      ) : null}
      <p className="pointer-events-none absolute right-[6vw] bottom-[34px] text-[13px] text-signin-hint signin-phone:hidden">Move, hover or drag the coins</p>
    </div>
  )
}
