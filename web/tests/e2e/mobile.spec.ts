import { expect, test } from '@playwright/test'
import { cleanup, creds, expectNoHorizontalScroll, hasAdmin, seed, signIn, type Seeded } from './support'

test('Login works on a phone without sideways scroll', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByLabel('Email')).toBeVisible()
  await expectNoHorizontalScroll(page)
})

test.describe('signed in', () => {
  test.skip(!hasAdmin, 'Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD (a dev test admin) to run.')

  let s: Seeded | undefined
  test.beforeAll(async () => {
    s = await seed()
  })
  test.afterAll(async () => {
    await cleanup(s)
  })

  test('Today on a phone: stacked rows, the WhatsApp app button first, no sideways scroll', async ({ page }) => {
    await signIn(page, creds.admin.email, creds.admin.password)
    await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
    const row = page.getByRole('listitem').filter({ has: page.getByRole('link', { name: `E2E Test Clinic 1 ${s!.runId}` }) })
    const firstAction = row.getByRole('link').filter({ hasText: /WhatsApp|Call/ }).first()
    await expect(firstAction).toHaveText(/Open WhatsApp app/)
    await expect(row.getByRole('link', { name: /Open WhatsApp Web/ })).toBeHidden()
    await expectNoHorizontalScroll(page)
  })
})
