import Link from 'next/link'
import { Wordmark } from '@/components/ui2/large-title'
import { SidebarSearch } from './search-trigger'

/** The laptop sidebar (from 1024 px), as in the mockups: wordmark, search, the places, the account at the foot. */
export function Sidebar({ links, account }: { links: React.ReactNode; account: React.ReactNode }) {
  return (
    <aside className="material-bar hairline-r fixed inset-y-0 left-0 z-30 hidden w-[var(--ui-sidebar-w)] flex-col px-4 pt-[30px] pb-[22px] lg:flex">
      <Link href="/" className="mb-[30px] self-start rounded-[8px] px-3" aria-label="nument, Today">
        <Wordmark className="text-[23px]" />
      </Link>
      <div className="mb-[22px]">
        <SidebarSearch />
      </div>
      <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {links}
      </nav>
      <div className="mt-3.5 shrink-0 border-t border-separator pt-3">{account}</div>
    </aside>
  )
}

/** Same size as the account row, while the session loads. */
export function AccountRowPlaceholder() {
  return <div aria-hidden className="h-11" />
}
