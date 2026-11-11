'use client'

import { DropdownMenu as M } from 'radix-ui'
import { cn } from '@/lib/cn'

export const Menu = M.Root
export const MenuTrigger = M.Trigger
export const MenuGroup = M.Group

export function MenuContent({ children, align = 'end', className }: { children: React.ReactNode; align?: 'start' | 'end' | 'center'; className?: string }) {
  return (
    <M.Portal>
      <M.Content
        align={align}
        sideOffset={6}
        className={cn('animate-pop-in shadow-menu z-50 min-w-48 rounded-xl border border-line bg-surface p-1', className)}
      >
        {children}
      </M.Content>
    </M.Portal>
  )
}

export function MenuItem({
  children,
  onSelect,
  danger,
  disabled,
  asChild,
}: {
  children: React.ReactNode
  onSelect?: (e: Event) => void
  danger?: boolean
  disabled?: boolean
  asChild?: boolean
}) {
  return (
    <M.Item
      asChild={asChild}
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        'flex h-9 cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 text-base outline-none [&_svg]:size-4 [&_svg]:text-tx-3',
        'data-[highlighted]:bg-surface-2 data-[disabled]:pointer-events-none data-[disabled]:opacity-45',
        danger ? 'text-bad [&_svg]:text-bad' : 'text-tx-1',
      )}
    >
      {children}
    </M.Item>
  )
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <M.Label className="label-mono px-2.5 pt-2 pb-1">{children}</M.Label>
}

export function MenuSeparator() {
  return <M.Separator className="my-1 h-px bg-line-2" />
}
