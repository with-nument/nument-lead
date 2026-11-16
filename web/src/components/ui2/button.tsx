import { cx } from './cx'

export type ButtonVariant = 'primary' | 'secondary' | 'plain' | 'destructive'
export type ButtonSize = 'small' | 'regular' | 'large'

const base =
  'relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap font-[525] ' +
  'transition-[background-color,border-color,color,opacity] duration-[var(--ui-dur-1)] ease-snap ' +
  'disabled:pointer-events-none [&:disabled:not([data-hydrating]):not([aria-busy])]:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40 ' +
  '[&_svg]:size-4 [&_svg]:shrink-0'

// One solid ink button per screen (primary); everything else is outlined or plain.
const variants: Record<ButtonVariant, string> = {
  primary: 'border border-accent-fill bg-accent-fill text-on-accent hover:border-accent-fill-hover hover:bg-accent-fill-hover',
  secondary: 'border border-separator-strong bg-panel text-label-1 hover:bg-fill-3',
  plain: 'border border-transparent text-label-2 hover:bg-fill-3 hover:text-label-1',
  destructive: 'border border-separator-strong bg-panel text-status-bad hover:bg-fill-3',
}

// 44 px on phones and tablets (a full tap target), 38 px with a mouse on laptops (the mockups).
const sizes: Record<ButtonSize, string> = {
  small: 'h-9 rounded-[10px] px-3 text-[13.5px] lg:h-8',
  regular: 'h-11 rounded-control px-[15px] text-[15px] lg:h-[38px] lg:text-[14px]',
  large: 'h-12 w-full rounded-[14px] px-5 text-[15px]',
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

/** A keyboard key hint, such as ⌘K or J. Inside the solid button it turns light. */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cx(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-[6px] border border-separator-strong bg-panel px-[5px] font-ui text-[11.5px] leading-none font-medium text-label-3',
        className,
      )}
    >
      {children}
    </kbd>
  )
}
