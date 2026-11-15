import type { Viewport } from 'next'
import { V2Scope } from '@/components/ui2/scope'
import { THEME_COLOR } from '@/styles/theme-color'

export const viewport: Viewport = { themeColor: THEME_COLOR, viewportFit: 'cover' }

/**
 * Sign-in, reset and new-password pages: a soft light wash (pure CSS, nothing to download) and one
 * frosted glass panel in the middle. Dark follows the system.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div data-ui="2" className="ui2-base relative isolate min-h-dvh">
      <V2Scope />
      <div aria-hidden className="wash-stage fixed inset-0 -z-10" />
      <main className="grid min-h-dvh place-items-center px-4 pt-[max(40px,env(safe-area-inset-top))] pb-[max(40px,env(safe-area-inset-bottom))]">
        <div className="material-window w-full max-w-[400px] rounded-window px-6 pt-9 pb-7 sm:px-9 sm:pt-11 sm:pb-9">{children}</div>
      </main>
    </div>
  )
}
