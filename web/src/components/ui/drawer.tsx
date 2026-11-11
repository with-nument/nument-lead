'use client'

import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

export const Drawer = D.Root
export const DrawerTrigger = D.Trigger
export const DrawerClose = D.Close

/** Slides in from the right on desktop, full screen on phones (plan 15.4.6). */
export function DrawerContent({
  title,
  children,
  className,
  side = 'right',
}: {
  title: string
  children: React.ReactNode
  className?: string
  side?: 'left' | 'right'
}) {
  return (
    <D.Portal>
      <D.Overlay className="animate-fade-in fixed inset-0 z-50 bg-[rgb(20_20_20/0.28)]" />
      <D.Content
        className={cn(
          'animate-drawer-in fixed inset-y-0 z-50 flex w-full flex-col bg-surface focus:outline-none sm:w-[380px]',
          side === 'right' ? 'right-0 sm:border-l sm:border-line' : 'left-0 sm:border-r sm:border-line',
          className,
        )}
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-line-2 px-4">
          <D.Title className="text-md font-medium text-tx-1">{title}</D.Title>
          <D.Description className="sr-only">{title}</D.Description>
          <D.Close className="grid size-10 place-items-center rounded-full text-tx-3 hover:bg-surface-2 hover:text-tx-1" aria-label="Close">
            <X className="size-4" />
          </D.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </D.Content>
    </D.Portal>
  )
}
