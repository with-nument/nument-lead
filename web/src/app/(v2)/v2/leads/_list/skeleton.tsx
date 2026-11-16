import { Skeleton } from '@/components/ui2/skeleton'
import { panel } from '../_ui/marks'

/** The Leads list's shape while it loads. */
export function LeadsSkeleton() {
  return (
    <div role="status" aria-label="Loading leads" className="mx-auto max-w-[1280px] px-4 pt-4 sm:px-6 lg:px-14 lg:pt-11">
      <Skeleton className="h-8 w-28" />
      <Skeleton className="mt-3 mb-5 h-4 w-52 lg:mb-8" />
      <div className="mb-4 flex flex-col gap-3 lg:mb-[22px] lg:flex-row">
        <Skeleton className="h-11 rounded-[14px] lg:h-[46px] lg:flex-1" />
        <Skeleton className="h-11 w-full rounded-[12px] lg:h-[38px] lg:w-[460px]" />
      </div>
      <div className={`${panel} overflow-hidden`}>
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="flex items-center gap-6 px-4 py-5 hairline-t first:shadow-none lg:px-[26px]">
            <Skeleton className="size-[18px] rounded-[5px]" />
            <div className="flex w-1/4 flex-col gap-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
            <Skeleton className="hidden size-6 rounded-[7px] lg:block" />
            <Skeleton className="hidden h-4 w-20 lg:block" />
            <Skeleton className="hidden h-4 flex-1 lg:block" />
            <Skeleton className="hidden h-4 w-28 lg:block" />
          </div>
        ))}
      </div>
    </div>
  )
}
