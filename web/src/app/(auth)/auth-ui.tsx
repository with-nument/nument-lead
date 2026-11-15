'use client'

import { useFormStatus } from 'react-dom'
import { ActivityIndicator } from '@/components/ui2/activity-indicator'
import { buttonClass } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { useHydrated } from '@/lib/use-hydrated'

// The sign-in pages are the first thing anyone loads, so they stay lean: no icon library and plain
// links between these static pages (next/link and lucide would add about 3.5 KB).

/** A short message under the fields: an error (announced at once) or a quiet confirmation. */
export function AuthAlert({ children, tone = 'error', id, className }: { children: React.ReactNode; tone?: 'error' | 'info'; id?: string; className?: string }) {
  return (
    <p id={id} role={tone === 'error' ? 'alert' : 'status'} className={cx('type-subhead px-4', tone === 'error' ? 'text-status-bad' : 'text-label-2', className)}>
      {children}
    </p>
  )
}

/**
 * The form's one primary button. It stays disabled until the page is interactive: with partial
 * prerendering, a form posted before hydration would get the cached shell back instead of running
 * its Server Action.
 */
export function AuthSubmit({ children, pendingLabel }: { children: string; pendingLabel: string }) {
  const { pending } = useFormStatus()
  const hydrated = useHydrated()
  return (
    <button
      type="submit"
      className={buttonClass('primary', 'large')}
      disabled={pending || !hydrated}
      data-hydrating={hydrated ? undefined : true}
      aria-busy={pending || undefined}
    >
      {pending ? <ActivityIndicator label={pendingLabel} /> : children}
    </button>
  )
}

/** Small text link under the button (a plain link: these pages are static and tiny). */
export function AuthLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <p className="mt-5 text-center">
      <a href={href} className="type-body rounded-[6px] text-accent underline-offset-4 hover:underline">
        {children}
      </a>
    </p>
  )
}

/** The eye in the password field (lucide's eye and eye-off, inlined). */
export function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="size-[18px]">
      {off ? (
        <>
          <path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49" />
          <path d="M14.084 14.158a3 3 0 0 1-4.242-4.242" />
          <path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143" />
          <path d="m2 2 20 20" />
        </>
      ) : (
        <>
          <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
          <circle cx="12" cy="12" r="3" />
        </>
      )}
    </svg>
  )
}
