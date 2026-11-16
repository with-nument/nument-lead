import Link from 'next/link'
import { buttonClass } from '@/components/ui2/button'
import { EmptyLine } from '@/components/ui2/empty-state'
import { CompanyMark, Note, TodayRow, TodaySection, Who } from './section'
import type { ProposalItem } from './types'

export type ProposalsSectionProps = {
  step: number
  items: ProposalItem[]
  primary?: boolean
}

/** Step 3: proposals drafted after a call, to review and send. */
export function ProposalsSection({ step, items, primary }: ProposalsSectionProps) {
  return (
    <TodaySection id="proposals" step={step} title="Proposals to send" count={items.length} collapsibleOnPhone defaultOpen={primary}>
      {items.length === 0 ? <EmptyLine>No proposals to send. After a call, the drafted proposal waits here for you.</EmptyLine> : null}
      {items.map((p, i) => (
        <TodayRow
          key={p.id}
          action={
            <Link href={p.href ?? `/leads/${p.leadId}`} className={buttonClass(primary && i === 0 ? 'primary' : 'secondary')}>
              Review and send
            </Link>
          }
        >
          <CompanyMark name={p.company} className="max-lg:hidden" />
          <div className="min-w-0 flex-1">
            <Who main={p.company} sub={p.person} />
            {p.note ? <Note>{p.note}</Note> : null}
          </div>
        </TodayRow>
      ))}
    </TodaySection>
  )
}
