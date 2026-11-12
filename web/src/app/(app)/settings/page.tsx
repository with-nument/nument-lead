import type { Metadata } from 'next'
import { Suspense } from 'react'
import { KeyRound } from 'lucide-react'
import { NameForm, PasswordForm, SessionButtons } from '@/components/settings/profile-forms'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { requireUser } from '@/lib/auth'
import { ROLE_HINT, ROLE_LABEL } from '@/lib/roles'

export const metadata: Metadata = { title: 'Settings' }

export default function SettingsPage({ searchParams }: PageProps<'/settings'>) {
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-2xl" />}>
      <Profile searchParams={searchParams} />
    </Suspense>
  )
}

async function Profile({ searchParams }: Pick<PageProps<'/settings'>, 'searchParams'>) {
  const [user, sp] = await Promise.all([requireUser(), searchParams])
  const forced = user.mustChangePassword || sp.change_password === '1'
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      {forced ? (
        <div role="alert" className="flex items-start gap-3 rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-3.5">
          <KeyRound aria-hidden className="mt-0.5 size-4 shrink-0 text-indigo-800" />
          <div>
            <p className="font-medium text-indigo-900">Choose your own password to continue</p>
            <p className="mt-0.5 text-base text-tx-2">You signed in with a temporary password. Set a new one below; the rest of the app opens right after.</p>
          </div>
        </div>
      ) : null}
      <Card aria-labelledby="password-title">
        <CardHeader id="password-title" title="Password" />
        <CardBody>
          <PasswordForm forced={forced} />
        </CardBody>
      </Card>
      <Card aria-labelledby="profile-title">
        <CardHeader id="profile-title" title="Profile" description={`Role: ${ROLE_LABEL[user.role]}. ${ROLE_HINT[user.role]}`} />
        <CardBody>
          <NameForm name={user.name} email={user.email} />
        </CardBody>
      </Card>
      <Card aria-labelledby="sessions-title">
        <CardHeader id="sessions-title" title="Sessions" description="Lost a phone or used a shared computer? Sign out everywhere else." />
        <CardBody>
          <SessionButtons />
        </CardBody>
      </Card>
    </div>
  )
}
