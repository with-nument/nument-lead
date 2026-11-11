import { cn } from '@/lib/cn'
import { Ornament } from './ornament'

/** One calm sentence and at most one action (plan 15.4.4), over the kit ornament. */
export function EmptyState({ text, action, className }: { text: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center px-6 py-12 text-center', className)}>
      <Ornament className="h-5 w-32 text-indigo-200" />
      <p className="mt-4 max-w-sm text-md text-tx-3">{text}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}
