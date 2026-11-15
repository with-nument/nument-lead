import type { Metadata } from 'next'
import { AuthHeading } from '../auth-heading'
import { ResetRequestForm } from './reset-request-form'

export const metadata: Metadata = { title: 'Reset password' }

export default function ResetPasswordPage() {
  return (
    <>
      <AuthHeading title="Reset your password" subtitle="We will email you a link to choose a new one." />
      <ResetRequestForm />
    </>
  )
}
