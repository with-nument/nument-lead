import Link from 'next/link'
import { Mark } from '@/components/brand/logo'

/** macOS-style translucent sidebar from 1024 px: brand, the places, the account at the foot. */
export function Sidebar({ links, account }: { links: React.ReactNode; account: React.ReactNode }) {
  return (
    <aside className="material-bar hairline-r fixed inset-y-0 left-0 z-30 hidden w-[var(--ui-sidebar-w)] flex-col lg:flex">
      <div className="flex h-[var(--ui-navbar-h)] shrink-0 items-center px-5">
        <Link href="/" className="flex items-center gap-2.5 rounded-[8px]" aria-label="Nument Leads, Today">
          <Mark className="size-6" />
          <span className="text-[15px] font-semibold tracking-[-0.01em] text-label-1">Nument Leads</span>
        </Link>
      </div>
      <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto px-3 pt-3 pb-4">
        {links}
      </nav>
      <div className="shrink-0 p-3 pt-0">{account}</div>
    </aside>
  )
}

/** Same size as the account row, while the session loads. */
export function AccountRowPlaceholder() {
  return <div aria-hidden className="h-11" />
}
