// Tiny shared store between the top bar button, the account menu and the tour itself, which
// stream in as separate parts of the shell. Also mirrors "tour done" in localStorage per user.
import { tourStorageKey } from '@/lib/tour'

type Listener = () => void
const listeners = new Set<Listener>()
let requests = 0
// Unknown until the tour has streamed in: a click that early is kept and opens the tour on arrival.
let enabled: boolean | null = null

const emit = () => listeners.forEach((l) => l())

export function subscribeTour(listener: Listener) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** How many times someone asked for the tour in this tab. Each new number starts it from the top. */
export const tourRequests = () => requests

/** Opens the tour from the first step (help button, account menu). Ignored while the tour cannot run. */
export function requestTour() {
  if (enabled === false) return
  requests += 1
  emit()
}

/** Set by the tour itself: off while a temporary password must be changed, which also drops early clicks. */
export function setTourEnabled(on: boolean | null) {
  enabled = on
  if (on === false && requests > 0) {
    requests = 0
    emit()
  }
}

export function readDoneLocally(userId: string): boolean {
  try {
    return window.localStorage.getItem(tourStorageKey(userId)) !== null
  } catch {
    return false
  }
}

export function markDoneLocally(userId: string) {
  try {
    window.localStorage.setItem(tourStorageKey(userId), new Date().toISOString())
  } catch {
    // Private mode or blocked storage: the server copy still stops the tour reopening.
  }
  emit()
}
