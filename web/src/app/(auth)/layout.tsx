import { Mark } from '@/components/brand/logo'
import { PixelField } from '@/components/auth/pixel-field'

/** Kit auth layout: an 8px frame, the woven PixelField panel on the left, the quiet form on the right. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-surface-2 p-2 md:grid-cols-[46fr_54fr]">
      <div className="relative hidden overflow-hidden rounded-l-lg bg-indigo-100 md:block">
        <PixelField className="absolute inset-0 touch-pan-y" />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-[linear-gradient(to_top,rgba(0,0,0,.72),rgba(0,0,0,.25)_45%,transparent)]"
        />
        <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 p-10 text-white">
          <div className="flex items-center gap-2">
            <Mark className="size-6" />
            <span className="wordmark text-[18px] text-white/85!">nument</span>
          </div>
          <p className="mt-3 max-w-md font-display text-[44px] leading-[1.02] font-normal tracking-[-0.015em] text-balance">
            Today&apos;s best leads, ready to send
          </p>
          <p className="mt-3 max-w-[330px] text-sm leading-relaxed text-white/65">
            Fresh leads every morning, each with dated evidence, a number the business published itself, and a first message written for them.
          </p>
        </div>
      </div>
      <div className="grid overflow-y-auto rounded-lg bg-surface px-4 py-12 md:rounded-l-none">
        <div className="m-auto w-full max-w-[340px]">{children}</div>
      </div>
    </div>
  )
}
