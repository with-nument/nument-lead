'use client'

import { useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { completeTour } from '@/app/(app)/tour-actions'
import { buttonClass } from '@/components/ui2/button'
import { Sheet, SheetContent } from '@/components/ui2/sheet'
import { tourStorageKey } from '@/lib/tour'

const STEPS = [
  { text: 'Read the morning email', when: '8 am' },
  { text: 'Approve replies to interested founders', when: '10 min' },
  { text: 'Take your calls', when: 'evening' },
  { text: 'Send the proposals we draft', when: '5 min each' },
] as const

/**
 * The `welcome-art` slot above the title: a path under /public (for example '/brand/welcome-coin.png'), or null
 * to show nothing. Kept empty until the final artwork is ready.
 */
export const WELCOME_ART: string | null = null

function WelcomeArt({ src }: { src: string | null }) {
  if (!src) return null
  return (
    <div data-slot="welcome-art" className="mb-[22px] flex justify-center">
      <Image src={src} alt="" width={112} height={112} priority className="size-24 lg:size-28" />
    </div>
  )
}

/** The welcome sheet itself, loaded only for someone who has not seen it (see WelcomeGate). */
export function WelcomeSheet({ userId }: { userId: string }) {
  const [closed, setClosed] = useState(false)

  function done() {
    setClosed(true)
    try {
      window.localStorage.setItem(tourStorageKey(userId), new Date().toISOString())
    } catch {
      // Private mode: the server copy below still keeps it closed.
    }
    void completeTour().catch(() => {})
  }

  return (
    <Sheet open={!closed} onOpenChange={(open) => (open ? null : done())}>
      <SheetContent
        variant="center"
        title="Welcome to Lead desk"
        hideHeader
        // Focus the sheet, not its last link, so nothing looks pressed before the person acts.
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          ;(e.currentTarget as HTMLElement | null)?.focus()
        }}
      >
        <div className="pt-4 lg:pt-12">
          <WelcomeArt src={WELCOME_ART} />
          <h2 className="text-center text-[26px] leading-tight font-semibold tracking-[-0.025em] text-label-1 lg:text-[30px]">Welcome to Lead desk</h2>
          <p className="mx-auto mt-2 max-w-[44ch] text-center text-[15px] text-label-3">
            We find startups that need a product team, write to them, and bring you the ones who reply.
          </p>
          <ol className="mt-[26px] mb-7">
            {STEPS.map((s, i) => (
              <li key={s.text} className="flex items-center gap-3.5 border-t border-separator py-3 text-[15.5px] text-label-1 first:border-t-0">
                <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full border border-separator-strong text-[12px] font-semibold text-label-2">
                  {i + 1}
                </span>
                <span className="flex-1">{s.text}</span>
                <span className="text-[13px] text-label-3">{s.when}</span>
              </li>
            ))}
          </ol>
          <Link href="/settings/email" onClick={done} className={buttonClass('primary', 'large', 'h-[54px] text-[16px]')}>
            Connect your mailbox <ArrowRight aria-hidden />
          </Link>
          <p className="mt-4 text-center text-[13px] text-label-3">
            Takes about a minute.{' '}
            <button type="button" onClick={done} className="inline-flex min-h-11 items-center text-label-1 underline decoration-separator-strong underline-offset-[3px] lg:min-h-0">
              You can look around first.
            </button>
          </p>
        </div>
      </SheetContent>
    </Sheet>
  )
}
