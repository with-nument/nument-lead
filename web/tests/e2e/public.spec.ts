import { expect, test } from '@playwright/test'

// Runs without any account: health, redirects, the sign-in errors and the reset answer.

test('health check answers without touching the database', async ({ request }) => {
  const res = await request.get('/api/health')
  expect(res.status()).toBe(200)
  const body = await res.json()
  expect(body.ok).toBe(true)
  expect(['dev', 'prod']).toContain(body.env)
  expect(res.headers()['cache-control']).toContain('no-store')
})

test('pages need a session and remember where you were going', async ({ page }) => {
  await page.goto('/leads?stage=talking')
  await expect(page).toHaveURL(/\/login\?next=%2Fleads%3Fstage%3Dtalking$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})

test('security headers are set', async ({ request }) => {
  const res = await request.get('/login')
  const h = res.headers()
  expect(h['x-frame-options']).toBe('DENY')
  expect(h['x-content-type-options']).toBe('nosniff')
  expect(h['referrer-policy']).toBe('strict-origin-when-cross-origin')
  expect(h['x-powered-by']).toBeUndefined()
})

test('a wrong password gets the same plain message as a wrong email', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill('nobody-e2e@example.com')
  await page.getByLabel('Password', { exact: true }).fill('not-the-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Email or password' })).toHaveText('Email or password is not right.')
  await expect(page).toHaveURL(/\/login/)
})

test('password reset answers the same for an unknown email', async ({ page }) => {
  await page.goto('/reset-password')
  await page.getByLabel('Email').fill('nobody-e2e@example.com')
  await page.getByRole('button', { name: 'Send reset link' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'If this email has an account' })).toBeVisible()
})

test('there is no public sign-up page', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByText('There is no public sign-up.')).toBeVisible()
  const res = await page.goto('/signup')
  expect(res?.url()).toContain('/login')
})
