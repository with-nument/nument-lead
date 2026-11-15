'use client'

import { Tooltip as T } from 'radix-ui'

/**
 * A short hint on hover or keyboard focus, after a calm delay. Never the only place information
 * lives: touch screens do not show tooltips.
 */
export function Tooltip({
  label,
  children,
  side = 'top',
}: {
  label: React.ReactNode
  /** The element that gets the hint; it must accept a ref and focus (a button or link). */
  children: React.ReactElement
  side?: 'top' | 'right' | 'bottom' | 'left'
}) {
  return (
    <T.Provider delayDuration={500} skipDelayDuration={300}>
      <T.Root>
        <T.Trigger asChild>{children}</T.Trigger>
        <T.Portal>
          <T.Content
            data-ui-motion
            side={side}
            sideOffset={6}
            collisionPadding={8}
            className="ui2-base motion-pop material-overlay type-caption z-50 max-w-[260px] rounded-[8px] px-2.5 py-1.5 font-medium"
          >
            {label}
          </T.Content>
        </T.Portal>
      </T.Root>
    </T.Provider>
  )
}
