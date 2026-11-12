'use client'

import { CircleHelp } from 'lucide-react'
import { requestTour } from './tour-store'

/** Small help button in the top bar that replays the product tour. */
export function TourButton() {
  return (
    <button
      type="button"
      onClick={requestTour}
      data-tour="tour-button"
      aria-label="Take the tour"
      title="Take the tour"
      className="grid size-10 place-items-center rounded-full text-tx-3 transition-colors hover:bg-surface-2 hover:text-tx-1"
    >
      <CircleHelp aria-hidden className="size-[18px]" strokeWidth={1.75} />
    </button>
  )
}
