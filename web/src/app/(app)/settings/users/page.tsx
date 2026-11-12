import type { Metadata } from 'next'
import { Suspense } from 'react'
import { CreateUserButton, UsersTable, type UserRow } from '@/components/settings/users-admin'
import { Card, CardHeader } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { requireRole } from '@/lib/auth'
import { relativeAge } from '@/lib/dates'
import { getUsers } from '@/lib/queries/settings'

export const metadata: Metadata = { title: 'Users and roles' }

export default function UsersPage() {
  return (
    <Suspense
      fallback={
        <Card>
          <SkeletonRows rows={3} />
        </Card>
      }
    >
      <Users />
    </Suspense>
  )
}

async function Users() {
  const me = await requireRole(['admin'])
  const users = await getUsers()
  const now = new Date()
  const rows: UserRow[] = users.map((u) => ({
    id: u.id,
    name: u.name,
    email: u.email,
    role: u.role,
    lastSignIn: u.lastSignInAt ? relativeAge(u.lastSignInAt, now) : '',
    disabled: u.disabled,
    mustChangePassword: u.mustChangePassword,
    isMe: u.id === me.id,
  }))
  return (
    <Card aria-labelledby="users-title" data-tour="settings-users">
      <CardHeader
        id="users-title"
        title={`Users · ${rows.length}`}
        description="Admins see everything. Callers send messages and move leads but never see money. Viewers only read."
        actions={<CreateUserButton />}
      />
      <div className="mt-3 border-t border-line-2">
        <UsersTable users={rows} />
      </div>
    </Card>
  )
}
