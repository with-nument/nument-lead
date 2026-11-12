import { expect, test } from '@playwright/test'
import { readRun, type Run } from './fixtures'
import { signIn } from './support'

// Moving between pages must be client-side routing: the sidebar stays put and no new document loads.
// A full page load here (a proxy redirect on an RSC request, an error in the app layout, a hard
// window.location change) is what reads as "the app reloads on every page". Read only.
test.describe.configure({ mode: 'serial' })

let run: Run
test.beforeAll(() => {
  run = readRun()
})

const PAGES = [
  ['Leads', '/leads'],
  ['Pipeline', '/pipeline'],
  ['Insights', '/insights'],
  ['Engine', '/engine'],
  ['Inbox', '/inbox'],
  ['Settings', '/settings'],
  ['Today', '/'],
] as const

test('sidebar links navigate without a document load, and the sidebar is never repainted', async ({ page }) => {
  await signIn(page, run.admin.email, run.admin.password)
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main' })
  // Wait for the role-aware sidebar (Engine is admin only), then tag its DOM node.
  await expect(nav.getByRole('link', { name: 'Engine', exact: true })).toBeVisible()
  await nav.evaluate((el) => el.setAttribute('data-e2e-nav-marker', 'kept'))

  const documents: string[] = []
  let loads = 0
  page.on('request', (r) => {
    if (r.resourceType() === 'document') documents.push(r.url())
  })
  page.on('load', () => loads++)

  for (const [label, path] of PAGES) {
    await nav.getByRole('link', { name: label, exact: true }).click()
    await page.waitForURL((u) => u.pathname === path)
    await expect(page.getByRole('heading', { level: 1, name: label === 'Today' ? 'Today' : label })).toBeVisible()
    await expect(nav.getByRole('link', { name: label, exact: true })).toHaveAttribute('aria-current', 'page')
  }

  expect(documents, 'document requests during sidebar navigation').toEqual([])
  expect(loads, 'load events during sidebar navigation').toBe(0)
  // Same DOM node all along: the sidebar was not torn down and rebuilt.
  await expect(nav).toHaveAttribute('data-e2e-nav-marker', 'kept')
})

test('opening a lead from the Leads list is client-side too', async ({ page }) => {
  await signIn(page, run.admin.email, run.admin.password)
  await page.goto(`/leads?q=${encodeURIComponent(run.runId)}`)
  const link = page.getByRole('link', { name: run.names.talking }).first()
  await expect(link).toBeVisible()
  let documents = 0
  page.on('request', (r) => {
    if (r.resourceType() === 'document') documents++
  })
  await link.click()
  await expect(page.getByRole('heading', { level: 1, name: run.names.talking })).toBeVisible()
  expect(documents).toBe(0)
})
