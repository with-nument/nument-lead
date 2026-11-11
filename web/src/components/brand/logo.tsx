import { cn } from '@/lib/cn'

/** The Nument mark (white glyph on indigo), drawn as SVG so it stays crisp at any size. */
export function Mark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 1024 1024" className={cn('shrink-0 rounded-[22%]', className)} role={title ? 'img' : undefined} aria-hidden={title ? undefined : true}>
      {title ? <title>{title}</title> : null}
      <rect width="1024" height="1024" fill="#2E2F9E" />
      <path fill="#fff" fillRule="evenodd" d="M275 275H749V595L595 749H275ZM373 373V498H512V637H637V373Z" />
    </svg>
  )
}

/** Mark plus the lowercase wordmark, with an optional product label. */
export function Logo({ className, product = 'Leads' }: { className?: string; product?: string | null }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <Mark className="size-6" />
      <span className="wordmark text-[20px]">nument</span>
      {product ? <span className="label-mono mt-0.5 text-tx-3">{product}</span> : null}
    </span>
  )
}
