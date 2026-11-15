'use client'

import { Popover as P } from 'radix-ui'
import { cx } from './cx'

export const Popover = P.Root
export const PopoverTrigger = P.Trigger
export const PopoverClose = P.Close
export const PopoverAnchor = P.Anchor

/** A small floating panel next to its trigger, on the overlay glass. */
export function PopoverContent({
  children,
  className,
  align = 'center',
  side = 'bottom',
  label,
}: {
  children: React.ReactNode
  className?: string
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** Accessible name for the panel. */
  label?: string
}) {
  return (
    <P.Portal>
      <P.Content
        data-ui-motion
        aria-label={label}
        align={align}
        side={side}
        sideOffset={8}
        collisionPadding={12}
        className={cx(
          'ui2-base motion-pop material-overlay z-50 max-w-[min(360px,calc(100vw-24px))] rounded-panel p-4 outline-none',
          className,
        )}
      >
        {children}
      </P.Content>
    </P.Portal>
  )
}
