// The sign-in form and the coins scene talk through one window event, so the form never imports
// three.js (the scene loads on its own, after the page is up).

export const SPIN_EVENT = 'nument:spin-coins'

/** Spins every coin once (Continue and Sign in). Does nothing if the scene is not running. */
export function spinCoins() {
  window.dispatchEvent(new Event(SPIN_EVENT))
}
