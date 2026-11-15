'use client'

import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { cx } from './cx'

export const Sheet = D.Root
export const SheetTrigger = D.Trigger
export const SheetClose = D.Close

/**
 * A sheet: rises from the bottom on phones and tablets, slides in as a side panel on laptops.
 * Escape, the close button or a tap outside dismisses it; focus is trapped while open.
 */
export function SheetContent({
  title,
  description,
  children,
  className,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <D.Portal>
      <D.Overlay data-ui-motion className="motion-fade fixed inset-0 z-50 bg-scrim" />
      <D.Content
        data-ui-motion
        className={cx(
          'ui2-base motion-sheet material-overlay fixed z-50 flex flex-col outline-none',
          'inset-x-0 bottom-0 max-h-[calc(100dvh-env(safe-area-inset-top)-24px)] rounded-t-sheet pb-[env(safe-area-inset-bottom)]',
          'lg:inset-y-0 lg:right-0 lg:left-auto lg:max-h-none lg:w-[420px] lg:rounded-none lg:pb-0',
          className,
        )}
      >
        <div aria-hidden className="mx-auto mt-1.5 h-[5px] w-9 shrink-0 rounded-full bg-fill-1 lg:hidden" />
        <div className="flex shrink-0 items-start justify-between gap-4 px-4 pt-3 pb-3 lg:px-5 lg:pt-5">
          <div className="min-w-0">
            <D.Title className="type-headline text-label-1">{title}</D.Title>
            {description ? (
              <D.Description className="type-subhead mt-0.5 text-label-3">{description}</D.Description>
            ) : (
              <D.Description className="sr-only">{title}</D.Description>
            )}
          </div>
          <D.Close
            aria-label="Close"
            className="-mt-0.5 -mr-1 grid size-[30px] shrink-0 place-items-center rounded-full bg-fill-1 text-label-2 transition-colors hover:bg-fill-2 [&_svg]:size-4"
          >
            <X aria-hidden strokeWidth={2.5} />
          </D.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4 lg:px-5 lg:pb-5">{children}</div>
      </D.Content>
    </D.Portal>
  )
}
