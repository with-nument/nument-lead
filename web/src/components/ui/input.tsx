import { forwardRef } from 'react'
import { cn } from '@/lib/cn'

export const fieldClasses =
  'w-full rounded-xl border border-line bg-surface px-3.5 text-lg text-tx-1 transition-[border-color,box-shadow] duration-150 sm:text-base ' +
  'placeholder:text-tx-4 hover:border-grey-400 focus-visible:outline-none focus-visible:focus-ring ' +
  'aria-invalid:border-red-300 aria-invalid:shadow-[var(--shadow-focus-error)] disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-tx-3'

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={cn(fieldClasses, 'h-10', className)} {...props} />
})

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={cn(fieldClasses, 'min-h-24 py-2.5 leading-6', className)} {...props} />
  },
)

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...props },
  ref,
) {
  return (
    <div className="relative">
      <select ref={ref} className={cn(fieldClasses, 'h-10 cursor-pointer appearance-none pr-9', className)} {...props}>
        {children}
      </select>
      <svg
        aria-hidden
        viewBox="0 0 16 16"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-tx-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="m4 6 4 4 4-4" />
      </svg>
    </div>
  )
})

export function Checkbox({ className, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type="checkbox"
      className={cn('size-4 shrink-0 cursor-pointer rounded-[4px] accent-[var(--color-ink)] disabled:cursor-not-allowed', className)}
      {...props}
    />
  )
}
