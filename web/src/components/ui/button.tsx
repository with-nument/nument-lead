import { forwardRef } from 'react'
import { Slot } from 'radix-ui'
import { cn } from '@/lib/cn'
import { Spinner } from './spinner'

export type ButtonVariant = 'primary' | 'secondary' | 'soft' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm'

const base =
  'relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium ' +
  'transition-[background-color,box-shadow,color,transform,filter] duration-300 ease-ui active:scale-[0.96] ' +
  'disabled:pointer-events-none disabled:opacity-45 aria-disabled:pointer-events-none aria-disabled:opacity-45 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 [&_svg]:size-4 [&_svg]:shrink-0'

const variants: Record<ButtonVariant, string> = {
  primary: 'btn-ink hover:brightness-[1.12]',
  secondary: 'bg-surface text-tx-1 shadow-[inset_0_0_0_1px_var(--color-st)] hover:bg-surface-2',
  soft: 'bg-surface-2 text-tx-1 shadow-[var(--shadow-btn-soft)] hover:bg-surface hover:shadow-[inset_0_0_0_1px_var(--color-st)]',
  ghost: 'text-tx-2 hover:bg-surface-2 hover:text-tx-1',
  danger: 'bg-surface text-bad shadow-[inset_0_0_0_1px_var(--color-st)] hover:bg-bad-bg',
}

const sizes: Record<ButtonSize, string> = {
  sm: 'h-10 px-3.5 text-sm sm:h-8 sm:px-3',
  md: 'h-10 px-4 text-base',
  lg: 'h-11 px-5 text-md',
  icon: 'size-10',
  'icon-sm': 'size-10 sm:size-8',
}

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  /** Render the child element (for example a Next Link) with button styles. */
  asChild?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, asChild = false, className, children, disabled, type, ...props },
  ref,
) {
  const classes = cn(base, variants[variant], sizes[size], className)
  if (asChild) {
    return (
      <Slot.Root ref={ref} className={classes} {...props}>
        {children}
      </Slot.Root>
    )
  }
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <>
          <span className="invisible inline-flex items-center gap-2">{children}</span>
          <span className="absolute inset-0 grid place-items-center">
            <Spinner />
          </span>
        </>
      ) : (
        children
      )}
    </button>
  )
})

export const buttonClasses = (variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', className?: string) =>
  cn(base, variants[variant], sizes[size], className)
