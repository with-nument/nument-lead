import { Mark } from '@/components/brand/logo'

/** The Nument mark, the page title and one line of help, centred at the top of the glass panel. */
export function AuthHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-7 flex flex-col items-center text-center">
      <Mark className="size-12 shadow-[var(--ui-shadow-panel)]" />
      <h1 className="mt-5 text-[28px] leading-[34px] font-bold tracking-[-0.021em] text-label-1">{title}</h1>
      {subtitle ? <p className="type-body mt-2 max-w-[30ch] text-balance text-label-2">{subtitle}</p> : null}
    </div>
  )
}
