'use client'

import { DropdownMenu as M } from 'radix-ui'
import { cx } from './cx'

export const Menu = M.Root
export const MenuTrigger = M.Trigger
export const MenuGroup = M.Group

/** A pull-down menu: a white card with a hairline edge and a soft shadow. */
export function MenuContent({
  children,
  align = 'end',
  side = 'bottom',
  className,
}: {
  children: React.ReactNode
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  className?: string
}) {
  return (
    <M.Portal>
      <M.Content
        data-ui-motion
        align={align}
        side={side}
        sideOffset={6}
        collisionPadding={12}
        className={cx('ui2-base motion-pop material-overlay z-50 min-w-[220px] rounded-[14px] p-1.5 outline-none', className)}
      >
        {children}
      </M.Content>
    </M.Portal>
  )
}

export function MenuItem({
  children,
  onSelect,
  destructive,
  disabled,
  asChild,
}: {
  children: React.ReactNode
  onSelect?: (e: Event) => void
  destructive?: boolean
  disabled?: boolean
  /** Render the child (for example a Next Link) as the item. */
  asChild?: boolean
}) {
  return (
    <M.Item
      asChild={asChild}
      disabled={disabled}
      onSelect={onSelect}
      className={cx(
        'flex h-11 cursor-default select-none items-center gap-3 rounded-[10px] px-3 text-[15px] outline-none lg:h-9 lg:gap-2.5 lg:text-[14px]',
        '[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:stroke-[1.6] data-[highlighted]:bg-fill-2 data-[disabled]:pointer-events-none data-[disabled]:opacity-40',
        destructive ? 'text-status-bad' : 'text-label-1 [&_svg]:text-label-3',
      )}
    >
      {children}
    </M.Item>
  )
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <M.Label className="type-caption px-3 pt-1.5 pb-1 text-label-3">{children}</M.Label>
}

export function MenuSeparator() {
  return <M.Separator className="mx-1.5 my-1.5 h-px bg-separator" />
}
