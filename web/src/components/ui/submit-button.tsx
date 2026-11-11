'use client'

import { useFormStatus } from 'react-dom'
import { useHydrated } from '@/lib/use-hydrated'
import { Button, type ButtonProps } from './button'

/** A submit button that shows a spinner while its form's Server Action runs. */
export function SubmitButton({ children, variant = 'primary', disabled, ...props }: ButtonProps) {
  const { pending } = useFormStatus()
  const hydrated = useHydrated()
  return (
    <Button type="submit" variant={variant} loading={pending} disabled={disabled || !hydrated} data-hydrating={hydrated ? undefined : true} {...props}>
      {children}
    </Button>
  )
}
