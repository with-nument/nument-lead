'use client'

import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { cx } from './cx'

export const Sheet = D.Root
export const SheetTrigger = D.Trigger
export const SheetClose = D.Close

/**
 * A sheet: rises from the bottom on phones and tablets, slides in as a side panel on laptops. `center`
 * is a calm dialog in the middle of the screen on laptops (the welcome sheet) and still a bottom sheet on
 * phones. Escape, the close button or a tap outside dismisses it; focus is trapped while open.
 */
export function SheetContent({
  title,
  description,
  children,
  className,
  variant = 'side',
  hideHeader,
  onEscapeKeyDown,
  onOpenAutoFocus,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  children: React.ReactNode
  className?: string
  variant?: 'side' | 'center'
  /** Keep the title for screen readers only (the content shows its own heading). */
  hideHeader?: boolean
  onEscapeKeyDown?: (e: KeyboardEvent) => void
  /** Called as the sheet opens; prevent the default to keep focus on the sheet itself, not its first control. */
  onOpenAutoFocus?: (e: Event) => void
}) {
  const center = variant === 'center'
  return (
    <D.Portal>
      <D.Overlay data-ui-motion className="motion-fade fixed inset-0 z-50 bg-scrim" />
      <D.Content
        data-ui-motion
        onEscapeKeyDown={onEscapeKeyDown}
        onOpenAutoFocus={onOpenAutoFocus}
        className={cx(
          'ui2-base fixed z-50 flex flex-col outline-none',
          'inset-x-0 bottom-0 max-h-[calc(100dvh-env(safe-area-inset-top)-24px)] rounded-t-sheet pb-[env(safe-area-inset-bottom)]',
          center
            ? 'motion-sheet-center material-window lg:inset-auto lg:top-1/2 lg:left-1/2 lg:max-h-[calc(100dvh-48px)] lg:w-[560px] lg:-translate-x-1/2 lg:-translate-y-1/2 lg:rounded-window lg:pb-0'
            : 'motion-sheet material-overlay lg:inset-y-0 lg:right-0 lg:left-auto lg:max-h-none lg:w-[440px] lg:rounded-none lg:pb-0',
          className,
        )}
      >
        <div aria-hidden className="mx-auto mt-2 h-[5px] w-9 shrink-0 rounded-full bg-fill-1 lg:hidden" />
        <div className={cx('flex shrink-0 items-start justify-between gap-4 px-5 pt-3 pb-3 lg:px-6 lg:pt-5', hideHeader && 'sr-only')}>
          <div className="min-w-0">
            <D.Title className="type-headline text-label-1">{title}</D.Title>
            {description ? (
              <D.Description className="type-subhead mt-0.5 text-label-3">{description}</D.Description>
            ) : (
              <D.Description className="sr-only">{title}</D.Description>
            )}
          </div>
          {hideHeader ? null : (
            <D.Close
              aria-label="Close"
              className="-mt-1 -mr-1.5 grid size-11 shrink-0 place-items-center rounded-control text-label-2 transition-colors hover:bg-fill-3 lg:size-9 [&_svg]:size-[18px]"
            >
              <X aria-hidden strokeWidth={1.6} />
            </D.Close>
          )}
        </div>
        <div className={cx('min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5 lg:px-6 lg:pb-6', center && 'lg:px-11 lg:pb-9')}>{children}</div>
      </D.Content>
    </D.Portal>
  )
}
