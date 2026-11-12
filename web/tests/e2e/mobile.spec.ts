import { expect, test } from '@playwright/test'
import { readRun, type Run } from './fixtures'
import { expectNoHorizontalScroll, signIn } from './support'

// Read after globalSetup has written it (test files are also loaded for listing).
let run: Run
test.beforeAll(() => {
  run = readRun()
})

test('Login works on a phone without sideways scroll', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByLabel('Email')).toBeVisible()
  await expectNoHorizontalScroll(page)
})

test('Today on a phone: the WhatsApp app button first, no sideways scroll', async ({ page }) => {
  await signIn(page, run.caller.email, run.caller.password)
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
  const row = page.getByRole('listitem').filter({ has: page.getByRole('link', { name: run.names.new1 }) })
  const firstAction = row.getByRole('link').filter({ hasText: /WhatsApp|Call/ }).first()
  await expect(firstAction).toHaveText(/Open WhatsApp app/)
  await expect(row.getByRole('link', { name: /Open WhatsApp Web/ })).toBeHidden()
  await expectNoHorizontalScroll(page)
})

test('Email recipients on a phone: labelled switches, no sideways scroll', async ({ page }) => {
  await signIn(page, run.admin.email, run.admin.password)
  await page.goto('/settings/email')
  await expect(page.getByRole('heading', { name: /Email recipients/ })).toBeVisible()
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible()
  await expectNoHorizontalScroll(page)
})
