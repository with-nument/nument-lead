'use client'

import { lazy, Suspense } from 'react'
import { ACCOUNT_ROW, AccountRowBody, PHONE_ACCOUNT, type AccountView } from './account-row'
import { Avatar } from './avatar'

// The account menu and sheet (their menu and dialog code) are split from the shell's first load. The server
// renders them as usual; in the browser the same row and avatar stay on screen until their code arrives.
const AccountMenu = lazy(() => import('./account-controls').then((m) => ({ default: m.AccountMenu })))
const AccountSheet = lazy(() => import('./account-controls').then((m) => ({ default: m.AccountSheet })))

export function LazyAccountMenu({ account }: { account: AccountView }) {
  return (
    <Suspense
      fallback={
        <button type="button" aria-label="Account" className={ACCOUNT_ROW}>
          <AccountRowBody account={account} />
        </button>
      }
    >
      <AccountMenu account={account} />
    </Suspense>
  )
}

export function LazyAccountSheet({ account }: { account: AccountView }) {
  return (
    <Suspense
      fallback={
        <button type="button" aria-label="Account" className={PHONE_ACCOUNT}>
          <Avatar initials={account.initials} />
        </button>
      }
    >
      <AccountSheet account={account} />
    </Suspense>
  )
}
