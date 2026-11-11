import Link from 'next/link'
import { Suspense } from 'react'
import { Logo } from '@/components/brand/logo'
import { NavLinksStatic } from '@/components/shell/nav'
import { AccountMenu, MobileMenu, SidebarNav, TopbarStatus } from '@/components/shell/shell-parts'

/**
 * App shell. The frame (sidebar, top bar, page area) is prerendered; everything that depends on
 * the signed-in user streams in behind Suspense, so navigation never waits on the session.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-full focus:bg-surface focus:px-4 focus:py-2 focus:shadow-menu">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line-2 bg-surface lg:flex">
        <div className="flex h-14 shrink-0 items-center px-5">
          <Link href="/" aria-label="Nument Leads, Today">
            <Logo />
          </Link>
        </div>
        <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pt-3">
          <Suspense fallback={<NavLinksStatic />}>
            <SidebarNav />
          </Suspense>
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line-2 bg-canvas/90 px-4 backdrop-blur-sm md:px-8">
          <Suspense fallback={<span className="size-10 lg:hidden" />}>
            <div className="lg:hidden">
              <MobileMenu />
            </div>
          </Suspense>
          <Link href="/" className="lg:hidden" aria-label="Nument Leads, Today">
            <Logo product={null} />
          </Link>
          <div className="ml-auto flex items-center gap-3">
            <Suspense fallback={null}>
              <TopbarStatus />
            </Suspense>
            <Suspense fallback={<span className="size-10 rounded-full bg-surface-2" />}>
              <AccountMenu />
            </Suspense>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1280px] px-4 pt-6 pb-16 md:px-8 md:pt-8">
          {children}
        </main>
      </div>
    </div>
  )
}
