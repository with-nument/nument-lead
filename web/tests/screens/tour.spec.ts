import path from 'node:path'
import { expect, test } from '@playwright/test'
import { readRun, type Run } from '../e2e/fixtures'
import { signIn } from '../e2e/support'

// Visual review of the product tour: one screenshot per step, as admin and caller, desktop and phone.
// Run with: SHOTS_DIR=/abs/path pnpm exec playwright test -c playwright.screens.config.ts tour
// Add E2E_FIXTURE_LEADS=0 SHOTS_TAG=empty to see it with no leads at all.
let run: Run
test.beforeAll(() => {
  run = readRun()
})

const dir = process.env.SHOTS_DIR ?? 'test-results/screens'
const tag = process.env.SHOTS_TAG ? `-${process.env.SHOTS_TAG}` : ''

for (const role of ['admin', 'caller'] as const) {
  test(`tour as ${role}`, async ({ page }, info) => {
    const device = info.project.name
    const user = role === 'admin' ? run.tourAdmin : run.tourCaller
    await signIn(page, user.email, user.password)
    const tour = page.getByTestId('tour')
    // First project to run gets the tour by itself; the next one replays it from the help button.
    await page.waitForTimeout(1500)
    if (!(await tour.isVisible())) await page.getByRole('button', { name: 'Take the tour' }).click()
    for (let i = 1; i <= 40; i++) {
      await expect(tour).toHaveAttribute('data-ready', 'true')
      await page.waitForTimeout(300) // let the card fade in
      const id = (await tour.getAttribute('data-step')) ?? 'step'
      await page.screenshot({ path: path.join(dir, `tour-${role}-${device}${tag}-${String(i).padStart(2, '0')}-${id}.png`) })
      const done = tour.getByRole('button', { name: 'Done' })
      if (await done.isVisible()) {
        await done.click()
        break
      }
      await tour.getByRole('button', { name: /^(Next|Show me around)$/ }).click()
      await expect(tour).not.toHaveAttribute('data-step', id)
    }
    await expect(tour).toBeHidden()
  })
}
