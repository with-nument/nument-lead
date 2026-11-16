import Link from 'next/link'
import { buttonClass } from '@/components/ui2/button'
import { EmptyLine } from '@/components/ui2/empty-state'
import { Note, PersonMark, TodayRow, TodaySection, Who } from './section'
import type { CallItem } from './types'

export type CallsSectionProps = {
  step: number
  items: CallItem[]
  primary?: boolean
}

/** Step 2: calls booked for today, earliest first, each with its brief. */
export function CallsSection({ step, items, primary }: CallsSectionProps) {
  return (
    <TodaySection id="calls" step={step} title="Calls today" count={items.length} collapsibleOnPhone={items.length === 0} defaultOpen={primary}>
      {items.length === 0 ? <EmptyLine>No calls booked for today. Calls that founders book from a reply show up here with a brief.</EmptyLine> : null}
      {items.map((c, i) => (
        <TodayRow
          key={c.id}
          action={
            <Link href={c.href ?? `/leads/${c.leadId}`} className={buttonClass(primary && i === 0 ? 'primary' : 'secondary')}>
              Open brief
            </Link>
          }
        >
          <span className="w-16 shrink-0 text-[15px] font-[550] whitespace-nowrap tabular-nums">{c.time}</span>
          <PersonMark name={c.person} />
          <div className="min-w-0 flex-1">
            <Who main={c.person} sub={c.company} />
            {c.note ? <Note>{c.note}</Note> : null}
          </div>
        </TodayRow>
      ))}
    </TodaySection>
  )
}
