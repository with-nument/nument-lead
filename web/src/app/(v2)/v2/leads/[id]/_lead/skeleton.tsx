import { Skeleton } from '@/components/ui2/skeleton'
import { panel } from '../../_ui/marks'

/** The lead page's shape while it loads: header, segments, the evidence panel and the side panel. */
export function LeadSkeleton() {
  return (
    <div role="status" aria-label="Loading the lead" className="mx-auto max-w-[1280px] px-4 pt-3 sm:px-6 lg:px-14 lg:pt-11">
      <Skeleton className="mb-[18px] hidden h-3.5 w-32 lg:block" />
      <Skeleton className="mb-4 h-6 w-20 lg:hidden" />
      <div className="mb-[26px] flex items-center gap-[18px]">
        <Skeleton className="size-11 rounded-[12px]" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-7 w-48" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        <Skeleton className="hidden h-12 w-44 rounded-[14px] lg:block" />
      </div>
      <Skeleton className="mb-[18px] h-11 w-full rounded-control lg:h-[38px] lg:w-[455px]" />
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className={`${panel} flex flex-col gap-4 p-6`}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-3 w-40" />
            </div>
          ))}
        </div>
        <div className={`${panel} hidden flex-col gap-4 p-6 lg:flex`}>
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-9 w-40" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-16 w-full" />
        </div>
      </div>
    </div>
  )
}
