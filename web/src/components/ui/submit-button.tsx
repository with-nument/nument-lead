'use client'

import { useFormStatus } from 'react-dom'
import { Button, type ButtonProps } from './button'

/** A submit button that shows a spinner while its form's Server Action runs. */
export function SubmitButton({ children, variant = 'primary', ...props }: ButtonProps) {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" variant={variant} loading={pending} {...props}>
      {children}
    </Button>
  )
}
