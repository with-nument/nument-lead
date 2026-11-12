'use client'

import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({
  title,
  description,
  children,
  className,
  wide,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  children: React.ReactNode
  className?: string
  wide?: boolean
}) {
  return (
    <D.Portal>
      <D.Overlay className="animate-fade-in fixed inset-0 z-50 bg-[rgb(20_20_20/0.32)]" />
      <D.Content
        className={cn(
          'animate-pop-in shadow-dialog fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-32px)] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-line bg-surface p-5 focus:outline-none sm:p-6',
          wide ? 'max-w-xl' : 'max-w-md',
          className,
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <D.Title className="text-xl font-medium text-tx-1">{title}</D.Title>
            {description ? <D.Description className="mt-1 text-base text-tx-3">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
          </div>
          <D.Close className="-m-1 grid size-9 shrink-0 place-items-center rounded-full text-tx-3 hover:bg-surface-2 hover:text-tx-1" aria-label="Close">
            <X className="size-4" />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  )
}
