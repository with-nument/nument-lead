import { cn } from '@/lib/cn'

export const authInput =
  'h-11 w-full rounded-full border border-line bg-surface px-4 text-lg text-tx-1 transition-[border-color,box-shadow] duration-150 sm:text-md ' +
  'placeholder:text-tx-4 focus-visible:outline-none focus-visible:focus-ring aria-invalid:border-red-300 aria-invalid:shadow-[var(--shadow-focus-error)]'

export const authPrimary =
  'relative inline-flex h-11 w-full items-center justify-center rounded-full bg-[var(--color-ink-auth)] px-4 text-md font-medium text-white transition-[background-color,transform] duration-300 ease-ui ' +
  'hover:bg-[var(--color-ink)] active:scale-[0.98] [&:disabled:not([data-hydrating]):not([aria-busy])]:bg-surface-3 [&:disabled:not([data-hydrating]):not([aria-busy])]:text-tx-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400'

export function AuthAlert({ children, tone = 'error', className }: { children: React.ReactNode; tone?: 'error' | 'info'; className?: string }) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn(
        'rounded-xl border px-3 py-2.5 text-sm',
        tone === 'error' ? 'border-[rgb(184_21_20/0.3)] bg-red-50 text-red-600' : 'border-indigo-200 bg-indigo-50 text-indigo-900',
        className,
      )}
    >
      {children}
    </div>
  )
}
