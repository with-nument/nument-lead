import Link from 'next/link'
import { Mark } from '@/components/brand/logo'
import { buttonClasses } from '@/components/ui/button'

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center bg-canvas px-6">
      <div className="flex flex-col items-center text-center">
        <Mark className="size-10" />
        <h1 className="mt-6 font-display text-title text-tx-1">This page does not exist.</h1>
        <p className="mt-2 text-md text-tx-3">The link may be old, or the page has moved.</p>
        <Link href="/" className={buttonClasses('primary', 'md', 'mt-6')}>
          Go to Today
        </Link>
      </div>
    </main>
  )
}
