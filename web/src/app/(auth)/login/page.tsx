import type { Metadata } from 'next'
import { AuthHeading } from '../auth-heading'
import { LoginForm } from './login-form'

export const metadata: Metadata = { title: 'Sign in' }

export default function LoginPage() {
  return (
    <>
      <AuthHeading title="Sign in" subtitle="Use the email and password your admin gave you." />
      <LoginForm />
    </>
  )
}
