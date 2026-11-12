import { expect, type Page } from '@playwright/test'
import { createClient } from '@supabase/supabase-js'
import type { Database } from '../../src/lib/database.types'

// The founder's real account is only used by founder.spec.ts, from environment variables.
export const founder = { email: process.env.E2E_FOUNDER_EMAIL ?? '', password: process.env.E2E_FOUNDER_PASSWORD ?? '' }
export const hasFounder = Boolean(founder.email && founder.password)

/** A browser-free client signed in as a user, to check what the database lets that user read. */
export async function userClient(email: string, password: string) {
  const sb = createClient<Database>(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
  const { error } = await sb.auth.signInWithPassword({ email, password })
  if (error) throw error
  return sb
}

export async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  // Wait until the sign in finished and the app took us somewhere, so the session cookie is set.
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}
