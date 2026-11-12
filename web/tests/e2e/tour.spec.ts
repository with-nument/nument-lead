import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { tourStepsFor } from '../../src/lib/tour'
import { readRun, serviceClient, type Run } from './fixtures'
import { signIn } from './support'

// The first-visit product tour, with the fresh tour users from globalSetup (no tour done yet).
// Nothing here changes a lead: the tour only reads pages and writes the user's own tour flag.
test.describe.configure({ mode: 'serial' })

let run: Run
test.beforeAll(() => {
  run = readRun()
})

const tour = (page: Page) => page.getByTestId('tour')

/** Waits until the card for this step is placed and shown. */
async function atStep(page: Page, id: string) {
  await expect(tour(page)).toHaveAttribute('data-step', id)
  await expect(tour(page)).toHaveAttribute('data-ready', 'true')
}

/** Clicks through every step and returns the ids and the page each one was shown on. */
async function walk(page: Page) {
  const seen: { id: string; path: string }[] = []
  for (let i = 0; i < 40; i++) {
    await expect(tour(page)).toHaveAttribute('data-ready', 'true')
    const id = (await tour(page).getAttribute('data-step')) ?? ''
    seen.push({ id, path: new URL(page.url()).pathname })
    const done = tour(page).getByRole('button', { name: 'Done' })
    if (await done.isVisible()) {
      await done.click()
      break
    }
    await tour(page).getByRole('button', { name: /^(Next|Show me around)$/ }).click()
    await expect(tour(page)).not.toHaveAttribute('data-step', id)
  }
  return seen
}

async function tourDoneOnServer(userId: string) {
  const { data } = await serviceClient().auth.admin.getUserById(userId)
  return (data.user?.user_metadata as Record<string, unknown> | undefined)?.tour_completed_at ?? null
}

test('Caller: the tour opens on the first visit with caller steps only, and finishing it sticks', async ({ page, browser }) => {
  test.setTimeout(120_000)
  expect(await tourDoneOnServer(run.tourCaller.id)).toBeNull()
  await signIn(page, run.tourCaller.email, run.tourCaller.password)
  await atStep(page, 'welcome')
  await expect(tour(page).getByRole('heading', { name: 'Welcome to Nument Leads' })).toBeVisible()
  await expect(tour(page)).toHaveAttribute('role', 'dialog')

  const seen = await walk(page)
  expect(seen.map((s) => s.id)).toEqual(tourStepsFor('caller').map((s) => s.id))
  for (const s of seen) expect(s.path).not.toMatch(/^\/(engine|inbox|settings\/users|settings\/suppression)/)
  // With fixture leads on the board, the lead page steps open a real lead.
  for (const s of seen.filter((x) => x.id.startsWith('lead-'))) expect(s.path).toMatch(/^\/leads\/[0-9a-f-]{36}$/)
  await expect(tour(page)).toBeHidden()

  await expect.poll(() => tourDoneOnServer(run.tourCaller.id)).not.toBeNull()

  // Same browser after a reload, and a fresh browser with empty storage: no tour either way.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
  await page.waitForTimeout(1200)
  await expect(tour(page)).toBeHidden()

  const ctx = await browser.newContext()
  const other = await ctx.newPage()
  await signIn(other, run.tourCaller.email, run.tourCaller.password)
  await expect(other.getByRole('heading', { name: 'Today' })).toBeVisible()
  await other.waitForTimeout(1200)
  await expect(tour(other)).toBeHidden()
  await ctx.close()
})

test('Replay from the help button and the account menu; keyboard, Esc and the focus trap work', async ({ page }) => {
  await signIn(page, run.tourCaller.email, run.tourCaller.password)
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()

  await page.getByRole('button', { name: 'Take the tour' }).click()
  await atStep(page, 'welcome')
  await expect(tour(page).getByRole('button', { name: 'Show me around' })).toBeFocused()

  // Arrow keys move between steps; the screen reader hears the step number.
  await page.keyboard.press('ArrowRight')
  await atStep(page, 'today-numbers')
  await expect(tour(page).locator('[aria-live="polite"]')).toHaveText(/^Step 2 of \d+: Your day at a glance$/)
  await page.keyboard.press('ArrowLeft')
  await atStep(page, 'welcome')

  // Tab never leaves the card.
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[data-testid="tour"]')))).toBe(true)
  }

  await page.keyboard.press('Escape')
  await expect(tour(page)).toBeHidden()

  await page.getByRole('button', { name: /Account menu for/ }).click()
  await page.getByRole('menuitem', { name: 'Take the tour' }).click()
  await atStep(page, 'welcome')
  await tour(page).getByRole('button', { name: 'Close the tour' }).click()
  await expect(tour(page)).toBeHidden()
})

test('Admin: gets every page, the deal card and the admin pages, and the card passes axe', async ({ page }) => {
  test.setTimeout(150_000)
  await signIn(page, run.tourAdmin.email, run.tourAdmin.password)
  await atStep(page, 'welcome')
  const results = await new AxeBuilder({ page }).include('[data-testid="tour"]').withTags(['wcag2a', 'wcag2aa']).analyze()
  expect(results.violations.map((v) => v.id)).toEqual([])

  const seen = await walk(page)
  expect(seen.map((s) => s.id)).toEqual(tourStepsFor('admin').map((s) => s.id))
  const where = Object.fromEntries(seen.map((s) => [s.id, s.path]))
  expect(where['engine-budget']).toBe('/engine')
  expect(where['inbox']).toBe('/inbox')
  expect(where['users']).toBe('/settings/users')
  expect(where['do-not-contact']).toBe('/settings/suppression')
  expect(where['lead-deal']).toMatch(/^\/leads\/[0-9a-f-]{36}$/)
  expect(where['done']).toBe('/')
  await expect.poll(() => tourDoneOnServer(run.tourAdmin.id)).not.toBeNull()
})

test('Skip at any step closes the tour and counts as done', async ({ page }) => {
  await signIn(page, run.tourAdmin.email, run.tourAdmin.password)
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
  await page.getByRole('button', { name: 'Take the tour' }).click()
  await atStep(page, 'welcome')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await atStep(page, 'today-send-list')
  await tour(page).getByRole('button', { name: 'Skip tour' }).click()
  await expect(tour(page)).toBeHidden()
  await page.goto('/leads')
  await page.waitForTimeout(1200)
  await expect(tour(page)).toBeHidden()
})

test('Waits for the forced password change, then opens on Today', async ({ page }) => {
  await signIn(page, run.tourNew.email, run.tourNew.password)
  await expect(page).toHaveURL(/\/settings\?change_password=1$/)
  await page.waitForTimeout(1200)
  await expect(tour(page)).toBeHidden()
  // Even the help button does nothing until the password is changed.
  await page.getByRole('button', { name: 'Take the tour' }).click()
  await page.waitForTimeout(500)
  await expect(tour(page)).toBeHidden()

  const fresh = `Calm-Indigo-${run.runId}!7`
  await page.getByLabel('New password').fill(fresh)
  await page.getByLabel('Type it again').fill(fresh)
  await page.getByRole('button', { name: 'Set my password' }).click()
  await expect(page).toHaveURL(/\/$/)
  await atStep(page, 'welcome')
})
