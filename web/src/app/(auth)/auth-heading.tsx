import { Mark } from '@/components/brand/logo'

/** Small brand above the title on phones (the art panel carries it on larger screens). */
export function AuthHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-7 text-center">
      <div className="mb-5 flex items-center justify-center gap-2 md:hidden">
        <Mark className="size-6" />
        <span className="wordmark text-[20px]">nument</span>
      </div>
      <h1 className="font-display text-title font-medium text-[var(--color-ink-auth)]">{title}</h1>
      {subtitle ? <p className="mt-2 text-base text-tx-3">{subtitle}</p> : null}
    </div>
  )
}
