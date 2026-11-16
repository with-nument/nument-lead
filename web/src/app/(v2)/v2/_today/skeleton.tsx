import { Skeleton, SkeletonList } from '@/components/ui2/skeleton'

/** Today while it loads: the same header, steps and side card, so nothing jumps when it arrives. */
export function TodaySkeleton() {
  return (
    <div role="status" aria-label="Loading Today">
      <div className="mx-auto max-w-[1192px] px-4 pt-[calc(var(--ui-navbar-h)+8px)] pb-5 sm:px-6 lg:px-14 lg:pt-11 lg:pb-8">
        <Skeleton className="h-3.5 w-36" />
        <Skeleton className="mt-3 h-8 w-[min(520px,80%)]" />
        <Skeleton className="mt-3 h-4 w-[min(340px,60%)]" />
      </div>
      <div className="mx-auto grid max-w-[1192px] grid-cols-[minmax(0,1fr)] items-start gap-6 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-8 lg:px-14">
        <div className="flex flex-col gap-3 lg:gap-3.5">
          <SkeletonList header rows={2} action />
          <SkeletonList header rows={1} action />
          <SkeletonList header rows={1} action />
        </div>
        <div className="material-panel rounded-panel px-[22px] py-5 max-lg:hidden">
          <Skeleton className="h-4 w-24" />
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="flex justify-between py-3">
              <Skeleton className="h-3.5 w-28" />
              <Skeleton className="h-3.5 w-8" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
