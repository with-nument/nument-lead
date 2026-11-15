'use client'

import { useEffect } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui2/button'
import { EmptyState } from '@/components/ui2/empty-state'

/** A calm page-level error. The code matches the server log line on Render. */
export default function V2Error({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error)
  }, [error])
  const digest = error instanceof Error && 'digest' in error ? String((error as Error & { digest?: string }).digest ?? '') : ''
  return (
    <div role="alert" className="pt-[env(safe-area-inset-top)]">
      <EmptyState
        icon={<TriangleAlert />}
        title="Something went wrong on this page"
        action={
          <Button variant="primary" onClick={() => retry()}>
            Try again
          </Button>
        }
      >
        Your data is safe. Try again, and if it keeps happening, share this code: {digest || 'none'}.
      </EmptyState>
    </div>
  )
}
