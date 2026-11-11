import { expect, test } from '@playwright/test'
import { founder, hasFounder, signIn } from './support'

// The founder's real admin account. This spec signs in and checks the forced password change,
// but never submits a new password: the founder sets it himself.
test.skip(!hasFounder, 'Set E2E_FOUNDER_EMAIL and E2E_FOUNDER_PASSWORD to run.')

test('sign in with a temporary password leads to the forced password change', async ({ page }) => {
  await signIn(page, founder.email, founder.password)
  await expect(page).toHaveURL(/\/settings\?change_password=1$/)
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page.getByText('Choose your own password to continue')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Set my password' })).toBeVisible()

  // Any other page sends the user back until the password is changed.
  await page.goto('/leads')
  await expect(page).toHaveURL(/\/settings\?change_password=1$/)

  // A signed-in user never sees the login page.
  await page.goto('/login')
  await expect(page).not.toHaveURL(/\/login/)

  // Admin sees the admin tabs.
  await page.goto('/settings')
  await expect(page.getByRole('link', { name: 'Users and roles' })).toBeVisible()

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
})
