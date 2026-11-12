import Link from 'next/link'
import { buttonClasses } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'

export default function LeadNotFound() {
  return (
    <EmptyState
      className="py-24"
      text="This lead does not exist or you do not have access."
      action={
        <Link href="/leads" className={buttonClasses('secondary')}>
          Back to leads
        </Link>
      }
    />
  )
}
