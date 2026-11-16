import Link from 'next/link'
import { SearchX } from 'lucide-react'
import { EmptyState } from '@/components/ui2/empty-state'
import { outlineClass } from '../_ui/marks'

export default function LeadNotFound() {
  return (
    <EmptyState
      icon={<SearchX />}
      title="This lead is not here"
      action={
        <Link href="/leads" className={outlineClass()}>
          Back to Leads
        </Link>
      }
    >
      It may have been merged with a duplicate, or the link is wrong. Search for the company in Leads.
    </EmptyState>
  )
}
