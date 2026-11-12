'use client'

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Ornament } from '@/components/ui/ornament'
import { Spinner } from '@/components/ui/spinner'
import { completeTour } from '@/app/(app)/tour-actions'
import { cn } from '@/lib/cn'
import type { Role } from '@/lib/roles'
import { LEAD_ROUTE, needsNavigation, pickLeadPath, placeCard, routeOf, shouldAutoStart, stepText, tourStepsFor, type Rect, type Size } from '@/lib/tour'
import { markDoneLocally, readDoneLocally, setTourEnabled, subscribeTour, tourRequests } from './tour-store'

/** Space between the highlighted element and the ring around it. */
const PAD = 6
/** Longest wait for a page to stream in before the step falls back to a centred card. */
const MAX_WAIT_MS = 6000
/** Sticky top bar height plus breathing room, so a highlight never hides under it. */
const TOP_CLEARANCE = 72

type Found = { key: string; el: HTMLElement | null; selectors: readonly string[]; radius: number }

const selectorOf = (name: string) => `[data-tour="${name}"]`

function isShown(el: Element) {
  const r = el.getBoundingClientRect()
  if (r.width < 1 || r.height < 1) return false
  const style = window.getComputedStyle(el)
  return style.visibility !== 'hidden' && style.display !== 'none'
}

/** The first visible element for the step's targets, in the order the step lists them. */
function findTarget(names: readonly string[] | undefined): HTMLElement | null {
  for (const name of names ?? []) {
    for (const el of document.querySelectorAll<HTMLElement>(selectorOf(name))) if (isShown(el)) return el
  }
  return null
}

/** True while the page under the tour still shows its loading skeleton. */
const pageLoading = () => Boolean(document.querySelector('main .skeleton, main [role="status"][aria-label="Loading"]'))

/** In view: wholly visible below the top bar, or, for an element taller than the window, starting in its upper part. */
function inView(r: DOMRect) {
  const top = TOP_CLEARANCE - 8
  const bottom = window.innerHeight - 16
  if (r.top < top) return false
  return r.height <= bottom - top ? r.bottom <= bottom : r.top <= window.innerHeight * 0.4
}

const prefersReducedMotion =() => window.matchMedia('(prefers-reduced-motion: reduce)').matches

const toRect = (r: DOMRect): Rect => ({ top: r.top, left: r.left, width: r.width, height: r.height })

export function ProductTour({ userId, role, completedAt, mustChangePassword }: { userId: string; role: Role; completedAt: string | null; mustChangePassword: boolean }) {
  const steps = useMemo(() => tourStepsFor(role), [role])
  const router = useRouter()
  const pathname = usePathname()

  // Each request from the help button or the account menu is a new run from step one.
  const requests = useSyncExternalStore(subscribeTour, tourRequests, () => 0)
  // The server snapshot says "done" so nothing opens before the browser has checked localStorage.
  const doneLocally = useSyncExternalStore(subscribeTour, () => readDoneLocally(userId), () => true)
  const [closedAtRequest, setClosedAtRequest] = useState<number | null>(null)
  const auto = shouldAutoStart({ mustChangePassword, completedAt, doneLocally })
  const open = !mustChangePassword && (closedAtRequest === null ? auto || requests > 0 : requests > closedAtRequest)

  const [pos, setPos] = useState({ run: 0, index: 0 })
  const index = pos.run === requests ? pos.index : 0
  const step = steps[Math.min(index, steps.length - 1)]
  const last = index === steps.length - 1
  const stepKey = `${requests}:${index}`

  const leadPath = useRef<{ run: number; path: string | null } | null>(null)
  const saved = useRef(Boolean(completedAt))
  const nextRef = useRef<HTMLButtonElement>(null)

  const [found, setFound] = useState<Found | null>(null)
  const [rect, setRect] = useState<Rect | null>(null)
  const [view, setView] = useState<Size>({ width: 1280, height: 800 })
  const [card, setCard] = useState<Size | null>(null)
  const [slow, setSlow] = useState(false)

  const ready = found?.key === stepKey
  const target = ready ? found.el : null

  // Requests from the help button only count once the tour can actually run.
  useEffect(() => {
    setTourEnabled(!mustChangePassword)
    return () => setTourEnabled(null)
  }, [mustChangePassword])

  // Keep the server copy in step with this browser: a tour finished elsewhere stays closed here.
  useEffect(() => {
    if (completedAt && !readDoneLocally(userId)) markDoneLocally(userId)
  }, [completedAt, userId])

  const close = useCallback(() => {
    setClosedAtRequest(tourRequests())
    markDoneLocally(userId)
    if (!saved.current) {
      saved.current = true
      void completeTour().catch(() => {
        // Offline or signed out: the localStorage copy still keeps it closed on this device.
      })
    }
  }, [userId])

  const go = useCallback(
    (to: number) => {
      const next = steps[to]
      if (!next) return
      if (next.route === LEAD_ROUTE && leadPath.current?.run !== requests) {
        const hrefs = Array.from(document.querySelectorAll('main a[href^="/leads/"]'), (a) => a.getAttribute('href') ?? '')
        leadPath.current = { run: requests, path: pickLeadPath(window.location.pathname, hrefs) }
      }
      const route = routeOf(next, leadPath.current?.run === requests ? leadPath.current.path : null)
      setPos({ run: requests, index: to })
      if (needsNavigation(window.location.pathname, route)) router.push(route!)
      // Back to the first step removes the Back button; keep focus on the main action.
      if (to === 0) requestAnimationFrame(() => nextRef.current?.focus())
    },
    [requests, router, steps],
  )

  // Find the step's element once its page has loaded, scroll it into view, or settle on a centred card.
  useEffect(() => {
    if (!open || !step) return
    let cancelled = false
    let timer = 0
    let frame = 0
    const started = performance.now()
    const route = routeOf(step, leadPath.current?.run === requests ? leadPath.current.path : null)
    const tick = () => {
      if (cancelled) return
      const elapsed = performance.now() - started
      const onPage = !needsNavigation(window.location.pathname, route)
      const el = onPage ? findTarget(step.target) : null
      const settled = onPage && !pageLoading() && elapsed > 150
      if (el || settled || elapsed > MAX_WAIT_MS) {
        const show = () => {
          setFound({ key: stepKey, el, selectors: step.target ?? [], radius: el ? Number.parseFloat(window.getComputedStyle(el).borderTopLeftRadius) || 8 : 16 })
          setSlow(false)
        }
        const r = el?.getBoundingClientRect()
        if (!r || inView(r)) return show()
        window.scrollTo({ top: Math.max(0, window.scrollY + r.top - TOP_CLEARANCE), behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
        // Show the card once the scroll has come to rest, so it lands next to the element, not where it was.
        const settleStart = performance.now()
        let lastY = Number.NaN
        let still = 0
        const settle = () => {
          if (cancelled) return
          still = window.scrollY === lastY ? still + 1 : 0
          lastY = window.scrollY
          if (still >= 3 || performance.now() - settleStart > 1500) return show()
          frame = requestAnimationFrame(settle)
        }
        frame = requestAnimationFrame(settle)
        return
      }
      if (elapsed > 400) setSlow(true)
      timer = window.setTimeout(tick, 80)
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
      window.clearTimeout(timer)
    }
  }, [open, step, stepKey, requests, pathname])

  // Follow the highlighted element while the page scrolls, resizes or re-renders.
  useEffect(() => {
    if (!open || !ready) return
    let frame = 0
    let el = found.el
    const measure = () => {
      frame = 0
      if (el && !el.isConnected) el = findTarget(found.selectors)
      setRect(el ? toRect(el.getBoundingClientRect()) : null)
      setView({ width: window.innerWidth, height: window.innerHeight })
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    schedule()
    const ro = new ResizeObserver(schedule)
    if (el) ro.observe(el)
    window.addEventListener('scroll', schedule, { passive: true, capture: true })
    window.addEventListener('resize', schedule)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      ro.disconnect()
      window.removeEventListener('scroll', schedule, { capture: true })
      window.removeEventListener('resize', schedule)
    }
  }, [open, ready, found])

  // The card's own size, for placing it. The portal mounts after the first render, hence a ref callback.
  const cardRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const ro = new ResizeObserver(() => setCard({ width: node.offsetWidth, height: node.offsetHeight }))
    ro.observe(node)
    return () => ro.disconnect()
  }, [])

  if (!open || !step) return null

  const shownRect = target && rect ? rect : null
  const place = placeCard(shownRect, card ?? { width: 360, height: 220 }, view)
  const visible = ready && card !== null
  const body = stepText(step, Boolean(target))
  const welcome = step.id === 'welcome'

  return (
    <D.Root open onOpenChange={(o) => (o ? undefined : close())}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-[70]" data-testid="tour-overlay">
          {shownRect ? (
            <div
              aria-hidden
              className="pointer-events-none fixed transition-[top,left,width,height] duration-300 ease-ui motion-reduce:transition-none"
              style={{
                top: shownRect.top - PAD,
                left: shownRect.left - PAD,
                width: shownRect.width + PAD * 2,
                height: shownRect.height + PAD * 2,
                borderRadius: (found?.radius ?? 12) + PAD,
                boxShadow: '0 0 0 2px var(--indigo-300), 0 0 0 9999px rgb(20 20 20 / 0.32)',
              }}
            />
          ) : (
            <div aria-hidden className="pointer-events-none fixed inset-0 bg-[rgb(20_20_20/0.32)]" />
          )}
          {!ready && slow ? (
            <div className="fixed inset-0 grid place-items-center text-white">
              <Spinner className="size-5" />
            </div>
          ) : null}
        </D.Overlay>
        <D.Content
          ref={cardRef}
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            nextRef.current?.focus()
          }}
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          onKeyDown={(e) => {
            if (e.altKey || e.ctrlKey || e.metaKey) return
            if (e.key === 'ArrowRight' && !last) {
              e.preventDefault()
              go(index + 1)
            } else if (e.key === 'ArrowLeft' && index > 0) {
              e.preventDefault()
              go(index - 1)
            }
          }}
          data-step={step.id}
          data-ready={visible}
          data-testid="tour"
          className={cn(
            'shadow-dialog fixed z-[71] rounded-2xl border border-line bg-surface p-5 transition-opacity duration-150 ease-ui focus:outline-none motion-reduce:transition-none',
            visible ? 'opacity-100' : 'pointer-events-none opacity-0',
          )}
          style={{ top: place.top, left: place.left, width: place.width }}
        >
          <div className="flex items-start justify-between gap-4">
            {welcome ? <Ornament className="mt-1 h-5 w-28 text-indigo-200" /> : <span aria-hidden className="label-mono pt-1">{`Step ${index + 1} of ${steps.length}`}</span>}
            <D.Close className="-mt-1.5 -mr-1.5 grid size-9 shrink-0 place-items-center rounded-full text-tx-3 hover:bg-surface-2 hover:text-tx-1" aria-label="Close the tour">
              <X className="size-4" />
            </D.Close>
          </div>
          <p className="sr-only" aria-live="polite" aria-atomic>
            {visible ? `Step ${index + 1} of ${steps.length}: ${step.title}` : ''}
          </p>
          <D.Title className={cn('text-tx-1', welcome ? 'mt-3 font-display text-title font-normal' : 'mt-2 text-xl font-medium')}>{step.title}</D.Title>
          <D.Description className="mt-2 text-base leading-6 text-pretty text-tx-2">
            {body}
          </D.Description>
          <div className="mt-5 flex items-center justify-between gap-2">
            {last ? (
              <span />
            ) : (
              <Button variant="ghost" size="sm" className="-ml-2 text-tx-3" onClick={close}>
                Skip tour
              </Button>
            )}
            <div className="flex items-center gap-2">
              {index > 0 ? (
                <Button variant="secondary" size="sm" onClick={() => go(index - 1)}>
                  Back
                </Button>
              ) : null}
              <Button ref={nextRef} variant="primary" size="sm" onClick={() => (last ? close() : go(index + 1))}>
                {welcome ? 'Show me around' : last ? 'Done' : 'Next'}
              </Button>
            </div>
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
