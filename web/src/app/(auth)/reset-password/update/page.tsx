import type { Metadata } from 'next'
import { AuthHeading } from '../../auth-heading'
import { NewPasswordForm } from './new-password-form'

export const metadata: Metadata = { title: 'Choose a new password' }

export default function UpdatePasswordPage() {
  return (
    <>
      <AuthHeading title="Choose a new password" subtitle="At least 12 characters, with upper and lower case letters, a number and a symbol." />
      <NewPasswordForm />
    </>
  )
}
