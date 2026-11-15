import type { Viewport } from 'next'
import { Suspense } from 'react'
import { PhoneAccount, RoleSidebarLinks, SidebarAccount } from '@/components/shell2/account'
import { AccountRowPlaceholder, Sidebar } from '@/components/shell2/sidebar'
import { SidebarLinks } from '@/components/shell2/sidebar-links'
import { TabBar } from '@/components/shell2/tab-bar'
import { NavAccessoryProvider } from '@/components/ui2/nav-accessory'
import { V2Scope } from '@/components/ui2/scope'
import { Toaster } from '@/components/ui2/toast'
import { THEME_COLOR } from '@/styles/theme-color'

export const viewport: Viewport = { themeColor: THEME_COLOR, viewportFit: 'cover' }

/**
 * The new design's shell. People reach these pages at their normal URLs: the proxy serves them from
 * /v2 when the `nl_ui=2` cookie is set (src/lib/ui-flag.ts). The frame prerenders; anything that
 * needs the signed-in user streams in behind Suspense, so navigation never waits on the session.
 */
export default function V2Layout({ children }: LayoutProps<'/v2'>) {
  return (
    <div data-ui="2" className="ui2-base relative isolate min-h-dvh">
      <V2Scope />
      <div aria-hidden className="wash fixed inset-0 -z-10" />
      <a
        href="#main"
        className="material-overlay sr-only z-50 rounded-control px-4 py-2 font-semibold text-accent focus:not-sr-only focus:fixed focus:top-[max(8px,env(safe-area-inset-top))] focus:left-2"
      >
        Skip to content
      </a>
      <Sidebar
        links={
          <Suspense fallback={<SidebarLinks role={null} />}>
            <RoleSidebarLinks />
          </Suspense>
        }
        account={
          <Suspense fallback={<AccountRowPlaceholder />}>
            <SidebarAccount />
          </Suspense>
        }
      />
      <NavAccessoryProvider
        value={
          <Suspense fallback={<span aria-hidden className="block size-11 lg:hidden" />}>
            <PhoneAccount />
          </Suspense>
        }
      >
        <div className="lg:pl-[var(--ui-sidebar-w)]">
          <main id="main" className="min-h-dvh pb-[calc(var(--ui-tabbar-h)+env(safe-area-inset-bottom)+40px)] lg:pb-20">
            {children}
          </main>
        </div>
      </NavAccessoryProvider>
      <TabBar />
      <Toaster />
    </div>
  )
}
