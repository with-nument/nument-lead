import type { Metadata } from 'next'
import { Suspense } from 'react'
import { AddSuppressionForm, RemoveSuppressionButton } from '@/components/settings/suppression-admin'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { SkeletonRows } from '@/components/ui/skeleton'
import { requireRole } from '@/lib/auth'
import { formatDate } from '@/lib/dates'
import { formatPhone } from '@/lib/phone'
import { getSuppression } from '@/lib/queries/settings'
import { getTeam } from '@/lib/queries/shared'
import { SUPPRESSION_REASON_LABEL } from '@/lib/suppression'

export const metadata: Metadata = { title: 'Do not contact' }

export default function SuppressionPage() {
  return (
    <Suspense
      fallback={
        <Card>
          <SkeletonRows rows={3} />
        </Card>
      }
    >
      <Suppression />
    </Suspense>
  )
}

async function Suppression() {
  await requireRole(['admin'])
  const [rows, team] = await Promise.all([getSuppression(), getTeam()])
  const names = new Map(team.map((m) => [m.id, m.name]))
  const now = new Date()
  const th = 'label-mono h-10 border-b border-line-2 px-3 font-normal whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5'
  const td = 'h-11 px-3 align-middle first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5'
  return (
    <div className="flex flex-col gap-6">
      <Card aria-labelledby="add-title">
        <CardHeader id="add-title" title="Add" description="The engine skips these and the app never offers them again." />
        <CardBody>
          <AddSuppressionForm />
        </CardBody>
      </Card>
      <Card aria-labelledby="list-title">
        <CardHeader id="list-title" title={`Do not contact · ${rows.length}`} />
        <div className="relative mt-3 overflow-x-auto border-t border-line-2">
          {rows.length ? (
            <table className="w-full text-left text-base">
              <thead>
                <tr>
                  <th scope="col" className={th}>Phone, email or website</th>
                  <th scope="col" className={th}>Reason</th>
                  <th scope="col" className={th}>Added by</th>
                  <th scope="col" className={th}>Date</th>
                  <th scope="col" className={th}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const label = r.phone_e164 ? formatPhone(r.phone_e164) : (r.email ?? r.web_domain ?? '')
                  return (
                    <tr key={r.id} className="border-b border-line-2 last:border-b-0">
                      <td className={`${td} tabular text-tx-1`}>{label}</td>
                      <td className={`${td} text-tx-2`}>{SUPPRESSION_REASON_LABEL[r.reason] ?? r.reason}</td>
                      <td className={`${td} text-tx-3`}>{r.added_by ? (names.get(r.added_by) ?? 'A teammate') : 'The engine'}</td>
                      <td className={`${td} whitespace-nowrap text-tx-3`}>{formatDate(r.added_at, now)}</td>
                      <td className={`${td} text-right`}>
                        <RemoveSuppressionButton id={r.id} label={label} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <EmptyState text="Nobody is on the do-not-contact list yet." />
          )}
        </div>
      </Card>
    </div>
  )
}
