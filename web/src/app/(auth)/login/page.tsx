import type { Metadata } from 'next'
import { AuthHeading } from '../auth-heading'
import { LoginForm } from './login-form'

export const metadata: Metadata = { title: 'Sign in' }

export default function LoginPage() {
  return (
    <>
      {/* The space before the break keeps the accessible name "Sign in to Nument Lead desk". */}
      <AuthHeading
        title={
          <>
            Sign in to <br />
            Nument Lead desk
          </>
        }
        subtitle="Find the founders who need a product team."
      />
      <LoginForm />
    </>
  )
}
