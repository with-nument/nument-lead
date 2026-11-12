import { Suspense } from 'react'
import { LinkTabs } from '@/components/ui/link-tabs'
import { PageHeader } from '@/components/ui/page-header'
import { requireUser } from '@/lib/auth'

async function Tabs() {
  const user = await requireUser()
  const tabs = [{ href: '/settings', label: 'Profile and password' }]
  if (user.role === 'admin') {
    tabs.push(
      { href: '/settings/users', label: 'Users and roles' },
      { href: '/settings/suppression', label: 'Do not contact' },
      { href: '/settings/email', label: 'Email recipients' },
    )
  }
  return <LinkTabs tabs={tabs} />
}

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Settings" />
      <Suspense fallback={<div className="mb-6 h-10 border-b border-line-2" />}>
        <Tabs />
      </Suspense>
      {children}
    </>
  )
}
