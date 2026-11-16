'use client'

import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { cx } from '@/components/ui2/cx'

/**
 * One numbered Today section (mockups): a white surface with a step number, a title and a count, then rows.
 * `collapsibleOnPhone` folds it to a single row on phones (tap to open), as the phone mockup does for the
 * later steps; laptops always show it open.
 */
export function TodaySection({
  step,
  title,
  count,
  countLabel,
  collapsibleOnPhone,
  defaultOpen,
  children,
  id,
}: {
  step: number
  title: string
  count: number
  /** Overrides the plain count, such as "2 left". */
  countLabel?: string
  collapsibleOnPhone?: boolean
  /** Starts open on phones (the section with the page's next step). */
  defaultOpen?: boolean
  children: React.ReactNode
  id: string
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen))
  const folded = collapsibleOnPhone && !open
  const head = (
    <>
      <StepMark n={step} />
      <h2 id={`${id}-title`} className="type-headline text-label-1">
        {title}
      </h2>
      <span className="text-[14px] text-label-3 tabular-nums">{countLabel ?? count}</span>
    </>
  )
  return (
    <section aria-labelledby={`${id}-title`} className="material-panel mb-3 overflow-hidden rounded-panel lg:mb-3.5">
      {collapsibleOnPhone ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex min-h-14 w-full items-center gap-3 px-4 text-left lg:hidden"
        >
          {head}
          <ChevronRight aria-hidden className={cx('ml-auto size-4 text-label-2 transition-transform', open && 'rotate-90')} strokeWidth={1.6} />
        </button>
      ) : null}
      <div className={cx('items-center gap-3 px-4 pt-[15px] pb-[13px] lg:px-[22px]', collapsibleOnPhone ? 'hidden lg:flex' : 'flex')}>{head}</div>
      <div className={cx('[&>*]:hairline-t', folded && 'max-lg:hidden')}>{children}</div>
    </section>
  )
}

export function StepMark({ n }: { n: number }) {
  return (
    <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full border border-separator-strong bg-panel text-[12px] font-semibold text-label-2">
      {n}
    </span>
  )
}

/** A person's initials in a grey circle (laptops only; the phone rows are text). */
export function PersonMark({ name }: { name: string | null }) {
  const letters =
    (name ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join('') || '·'
  return (
    <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full border border-separator bg-avatar text-[12.5px] font-semibold text-label-2 max-lg:hidden">
      {letters}
    </span>
  )
}

/** A company's first letter in a soft grey tile with a hairline edge (never a solid block). */
export function CompanyMark({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cx('grid size-8 shrink-0 place-items-center rounded-[9px] border border-separator bg-avatar text-[14px] font-semibold text-label-2', className)}
    >
      {(name.trim()[0] ?? '·').toUpperCase()}
    </span>
  )
}

/** "Name · Company" with the second part quiet. */
export function Who({ main, sub }: { main: string; sub?: string | null }) {
  return (
    <p className="truncate text-[15px] font-[550] text-label-1">
      {main}
      {sub ? <span className="font-normal text-label-3"> · {sub}</span> : null}
    </p>
  )
}

/** The quiet line under a row's name. */
export function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-0.5 truncate text-[13px] text-label-3">{children}</p>
}

/** A Today row: content, then the action (below the text on phones, at the end on laptops). */
export function TodayRow({ children, action, className }: { children: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cx('flex flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3.5 lg:flex-nowrap lg:px-[22px]', className)}>
      <div className="flex min-w-0 flex-1 basis-[60%] items-center gap-4">{children}</div>
      {action ? <div className="flex shrink-0 items-center gap-2 max-lg:w-full max-lg:[&>*]:flex-1">{action}</div> : null}
    </div>
  )
}
