'use client'

import { useFormStatus } from 'react-dom'
import { useHydrated } from '@/lib/use-hydrated'

// Shared pieces of the sign-in pages (the approved mock). These pages are the first thing anyone loads,
// so they stay lean: no icon library and plain links between these static pages.

/** Container for the fields: rises in with the button. */
export const signinFields = 'signin-rise mt-10 flex flex-col gap-3 [animation-delay:250ms]'

/** The message line under the fields: errors are announced at once, confirmations politely. Keeps its height. */
export function AuthMessage({ children, tone = 'error', id }: { children?: React.ReactNode; tone?: 'error' | 'info'; id?: string }) {
  return (
    <p id={id} role={tone === 'error' ? 'alert' : 'status'} className="mx-0.5 mt-2.5 min-h-5 text-[14px] leading-5 text-signin-ink">
      {children}
    </p>
  )
}

/** The small grey note under the button. */
export function AuthNote({ children }: { children: React.ReactNode }) {
  return <div className="signin-rise mt-7 text-center text-[14px] text-signin-label-3 [animation-delay:250ms]">{children}</div>
}

function Arrow() {
  return (
    <svg
      aria-hidden
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  )
}

/**
 * The page's one black button. It stays disabled until the page is interactive: with partial
 * prerendering, a form posted before hydration would get the cached shell back instead of running
 * its Server Action. It does not look disabled meanwhile.
 */
export function AuthButton({ children, pending, pendingLabel }: { children: string; pending: boolean; pendingLabel: string }) {
  const hydrated = useHydrated()
  return (
    <button
      type="submit"
      disabled={pending || !hydrated}
      aria-busy={pending || undefined}
      className="signin-button signin-rise [animation-delay:250ms]"
    >
      <span>{pending ? pendingLabel : children}</span>
      {pending ? null : <Arrow />}
    </button>
  )
}

/** AuthButton for forms that post straight to their Server Action (reset pages). */
export function AuthSubmit({ children, pendingLabel }: { children: string; pendingLabel: string }) {
  const { pending } = useFormStatus()
  return (
    <AuthButton pending={pending} pendingLabel={pendingLabel}>
      {children}
    </AuthButton>
  )
}
