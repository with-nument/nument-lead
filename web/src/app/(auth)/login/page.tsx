import type { Metadata } from 'next'
import { Suspense } from 'react'
import { AuthHeading } from '../auth-heading'
import { LoginForm } from './login-form'

export const metadata: Metadata = { title: 'Sign in' }

export default function LoginPage({ searchParams }: PageProps<'/login'>) {
  return (
    <>
      <AuthHeading title="Sign in" subtitle="Use the email and password your admin gave you." />
      <Suspense fallback={<LoginForm next="" linkError={false} />}>
        {searchParams.then((sp) => (
          <LoginForm next={typeof sp.next === 'string' ? sp.next : ''} linkError={sp.error === 'link'} />
        ))}
      </Suspense>
    </>
  )
}
