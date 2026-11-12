'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Ornament } from '@/components/ui/ornament'

/** Calm page-level error (plan 15.9). The digest matches the server log line on Render. */
export default function AppError({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error)
  }, [error])
  const digest = error instanceof Error && 'digest' in error ? String((error as Error & { digest?: string }).digest ?? '') : ''
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-24 text-center">
      <Ornament className="h-5 w-32 text-indigo-200" />
      <h1 className="mt-5 font-display text-title text-tx-1">Something went wrong on this page.</h1>
      <p className="mt-2 max-w-md text-md text-tx-3">Your data is safe. Try again, and if it keeps happening, share the code below.</p>
      <Button className="mt-6" variant="primary" onClick={() => retry()}>
        Try again
      </Button>
      {digest ? <p className="label-mono mt-6">Error {digest}</p> : null}
    </div>
  )
}
