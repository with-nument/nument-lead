import { Skeleton } from '@/components/ui2/skeleton'

/** The Inbox while it loads: the same two panels, list rows on the left, a message on the right. */
export function InboxSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="lg:-mb-20 lg:grid lg:h-dvh lg:grid-cols-[minmax(340px,5fr)_7fr] lg:gap-6 lg:p-6 xl:grid-cols-[minmax(380px,550px)_1fr]">
      <div className="flex flex-col lg:material-panel lg:overflow-hidden lg:rounded-panel">
        <div className="px-4 pt-4 pb-4 sm:px-6 lg:pt-6">
          <Skeleton className="h-8 w-28" />
          <Skeleton className="mt-5 h-9 w-72 rounded-[11px]" />
        </div>
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="hairline-t flex flex-col gap-2.5 py-5 pr-6 pl-9 lg:pl-11">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </div>
      <div className="hidden flex-col gap-6 p-8 lg:material-panel lg:flex lg:rounded-panel">
        <div className="flex items-center gap-4">
          <Skeleton className="size-[60px] rounded-full" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3.5 w-80" />
          </div>
        </div>
        <Skeleton className="h-12 w-full rounded-[14px]" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-3/5" />
        <Skeleton className="mt-4 h-72 w-full rounded-[18px]" />
      </div>
    </div>
  )
}
