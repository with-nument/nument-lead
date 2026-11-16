import { expect, type Page } from '@playwright/test'
import { createClient } from '@supabase/supabase-js'
import type { Database } from '../../src/lib/database.types'
import { LoginPage } from './pom/login-page'

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

/** Signs in through the page (both steps) and waits until the app took over, so the session cookie is set. */
export async function signIn(page: Page, email: string, password: string) {
  const login = new LoginPage(page)
  await login.goto()
  await login.signIn(email, password)
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}
