import { requireUser } from '@/lib/auth'
import { env } from '@/lib/env'
import { formatTime, formatDate, istDate } from '@/lib/dates'
import { getLastSheetSync } from '@/lib/queries/shell'
import { Tag } from '@/components/ui/badge'
import { ProductTour } from '@/components/tour/product-tour'
import { NavLinks } from './nav'
import { MobileNav } from './mobile-nav'
import { UserMenu } from './user-menu'

/** Role-aware sidebar links. Streams in after the session read; the shell shows a static list first. */
export async function SidebarNav() {
  const user = await requireUser()
  return <NavLinks role={user.role} />
}

export async function MobileMenu() {
  const user = await requireUser()
  return <MobileNav role={user.role} />
}

export async function TopbarStatus() {
  await requireUser()
  const { APP_ENV } = env()
  const synced = await getLastSheetSync()
  const now = new Date()
  const label = synced
    ? istDate(synced) === istDate(now)
      ? `Sheet synced ${formatTime(synced)}`
      : `Sheet synced ${formatDate(synced, now)}, ${formatTime(synced)}`
    : 'Sheet not synced yet'
  return (
    <div className="flex items-center gap-3">
      {APP_ENV === 'dev' ? (
        <Tag tone="warn" className="font-mono tracking-wide">
          DEV
        </Tag>
      ) : null}
      <span className="hidden text-sm text-tx-3 md:inline" title="The Google Sheet updates from this app at each sync">
        {label}
      </span>
    </div>
  )
}

/** The first-visit product tour. Opens by itself once, after any forced password change. */
export async function TourHost() {
  const user = await requireUser()
  return <ProductTour userId={user.id} role={user.role} completedAt={user.tourCompletedAt} mustChangePassword={user.mustChangePassword} />
}

export async function AccountMenu() {
  const user = await requireUser()
  return <UserMenu name={user.name} email={user.email} role={user.role} />
}
