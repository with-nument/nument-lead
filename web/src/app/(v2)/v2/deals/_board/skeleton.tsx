import { Skeleton } from '@/components/ui2/skeleton'
import { panel } from '../../leads/_ui/marks'

/** The Deals board's shape while it loads: five columns of cards. */
export function DealsSkeleton() {
  return (
    <div role="status" aria-label="Loading deals" className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-14 lg:pt-11">
      <Skeleton className="h-8 w-28" />
      <Skeleton className="mt-3 mb-5 h-4 w-64 lg:mb-8" />
      <div className={`${panel} -mx-4 overflow-hidden sm:mx-0`}>
        <div className="grid min-w-[1000px] grid-cols-5 lg:min-w-0">
          {Array.from({ length: 5 }, (_, c) => (
            <div key={c} className="flex flex-col gap-6 p-6">
              <Skeleton className="h-4 w-24" />
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="flex flex-col gap-2">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
