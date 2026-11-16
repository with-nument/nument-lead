import type { Role } from '@/lib/roles'
import { Avatar } from './avatar'

export type AccountView = { initials: string; role: Role; roleLabel: string; email: string }

export const ACCOUNT_ROW =
  'flex min-h-12 w-full items-center gap-2.5 rounded-control px-3 py-1.5 text-left transition-colors hover:bg-fill-3 data-[state=open]:bg-fill-2'
export const PHONE_ACCOUNT = '-mr-1.5 grid size-11 place-items-center rounded-full lg:hidden'

/** What the sidebar's account row shows: initials, role and email. */
export function AccountRowBody({ account }: { account: AccountView }) {
  return (
    <>
      <Avatar initials={account.initials} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-[14px] leading-tight font-[550] text-label-1">{account.roleLabel}</span>
        <span className="truncate text-[12.5px] text-label-3">{account.email}</span>
      </span>
    </>
  )
}
