import type { Metadata } from 'next'
import { Suspense } from 'react'
import { AddRecipientForm, RecipientsList } from '@/components/settings/email-admin'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { early, requireRole } from '@/lib/auth'
import { getRecipients } from '@/lib/queries/settings'
import { emailConfigured } from '@/lib/resend'

export const metadata: Metadata = { title: 'Email recipients' }

export default function EmailRecipientsPage() {
  return (
    <Suspense
      fallback={
        <Card>
          <SkeletonRows rows={3} />
        </Card>
      }
    >
      <EmailRecipients />
    </Suspense>
  )
}

async function EmailRecipients() {
  // Runs as the user (RLS: admin only) and starts while the role is checked.
  const rowsP = early(getRecipients())
  await requireRole(['admin'])
  const rows = await rowsP
  const canSend = emailConfigured()
  return (
    <div className="flex flex-col gap-6">
      <Card aria-labelledby="add-title">
        <CardHeader id="add-title" title="Add" description="New people get every email: the morning list, alerts and the weekly report. Switch any of them off below." />
        <CardBody>
          <AddRecipientForm />
        </CardBody>
      </Card>
      <Card aria-labelledby="list-title" data-tour="settings-email">
        <CardHeader
          id="list-title"
          title={`Email recipients · ${rows.length}`}
          description={
            canSend
              ? 'Each person gets their own email; nobody sees the others. Only admins see spend and money won.'
              : 'Each person gets their own email; nobody sees the others. Send test needs RESEND_API_KEY on this server.'
          }
        />
        <div className="mt-3 border-t border-line-2">
          <RecipientsList recipients={rows} />
        </div>
      </Card>
    </div>
  )
}
