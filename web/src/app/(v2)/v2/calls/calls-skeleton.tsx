import { Skeleton } from '@/components/ui2/skeleton'

/** Calls while they load: the list of calls on the left, the brief on the right. */
export function CallsSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="lg:-mb-20 lg:grid lg:h-dvh lg:grid-cols-[minmax(320px,4fr)_7fr] lg:gap-6 lg:p-6 xl:grid-cols-[minmax(360px,500px)_1fr]">
      <div className="flex flex-col lg:material-panel lg:overflow-hidden lg:rounded-panel">
        <div className="px-4 pt-4 pb-4 sm:px-6 lg:pt-6">
          <Skeleton className="h-8 w-24" />
        </div>
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="hairline-t flex items-center gap-4 px-6 py-5">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="size-9 rounded-full" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
      <div className="hidden flex-col gap-6 p-8 lg:material-panel lg:flex lg:rounded-panel">
        <div className="flex items-center gap-4">
          <Skeleton className="size-12 rounded-[12px]" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-5 w-64" />
            <Skeleton className="h-3.5 w-80" />
          </div>
        </div>
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-4/5" />
        <div className="grid grid-cols-2 gap-8">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-28 w-full rounded-[14px]" />
        <Skeleton className="h-28 w-full rounded-[14px]" />
      </div>
    </div>
  )
}
