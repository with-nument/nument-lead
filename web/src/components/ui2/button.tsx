import { cx } from './cx'

export type ButtonVariant = 'primary' | 'secondary' | 'plain' | 'destructive'
export type ButtonSize = 'small' | 'regular' | 'large'

const base =
  'relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-control font-semibold ' +
  'transition-[background-color,color,opacity,transform] duration-[var(--ui-dur-1)] ease-snap active:scale-[0.98] ' +
  'disabled:pointer-events-none [&:disabled:not([data-hydrating]):not([aria-busy])]:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40 ' +
  '[&_svg]:size-[1.1em] [&_svg]:shrink-0'

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-accent-fill text-on-accent hover:bg-accent-fill-hover',
  secondary: 'bg-fill-1 text-label-1 hover:bg-fill-2',
  plain: 'text-accent hover:bg-fill-3',
  destructive: 'bg-fill-1 text-status-bad hover:bg-fill-2',
}

// 44 px on phones and tablets (a full tap target), denser with a mouse on laptops.
const sizes: Record<ButtonSize, string> = {
  small: 'h-8 px-3 text-[15px] lg:h-7 lg:px-2.5 lg:text-[13px]',
  regular: 'h-11 px-5 text-[17px] lg:h-9 lg:px-4 lg:text-[15px]',
  large: 'h-[50px] w-full px-6 text-[17px] lg:h-11 lg:text-[15px]',
}

/** Button classes, for a Link that should look like a button. */
export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'regular', className?: string) {
  return cx(base, variants[variant], sizes[size], className)
}

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  ref?: React.Ref<HTMLButtonElement>
}

export function Button({ variant = 'secondary', size = 'regular', className, type, ...props }: ButtonProps) {
  return <button type={type ?? 'button'} className={buttonClass(variant, size, className)} {...props} />
}
