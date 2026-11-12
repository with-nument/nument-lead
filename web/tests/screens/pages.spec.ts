import path from 'node:path'
import { test, type Page } from '@playwright/test'
import { readRun, type Run } from '../e2e/fixtures'
import { signIn } from '../e2e/support'

let run: Run
test.beforeAll(() => {
  run = readRun()
})

const dir = process.env.SHOTS_DIR ?? 'test-results/screens'

async function settle(page: Page) {
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(700)
}

async function capture(page: Page, role: string, device: string, name: string, url: string) {
  await page.goto(url)
  await settle(page)
  const landed = new URL(page.url()).pathname
  const suffix = url.split('?')[0] !== landed && !(url === '/' && landed === '/') ? `-redirected-to-${landed.replace(/\//g, '') || 'today'}` : ''
  await page.screenshot({ path: path.join(dir, `${role}-${device}-${name}${suffix}.png`), fullPage: true })
}

for (const role of ['admin', 'caller'] as const) {
  test(`every page as ${role}`, async ({ page }, info) => {
    const device = info.project.name
    const user = run[role]
    await signIn(page, user.email, user.password)
    const pages: [string, string][] = [
      ['01-today', '/'],
      ['02-leads', '/leads'],
      ['03-lead', `/leads/${run.leadIds.proposal}`],
      ['04-pipeline', '/pipeline'],
      ['05-insights', '/insights'],
      ['06-engine', '/engine'],
      ['07-inbox', '/inbox'],
      ['08-settings', '/settings'],
      ['09-users', '/settings/users'],
      ['10-do-not-contact', '/settings/suppression'],
    ]
    for (const [name, url] of pages) await capture(page, role, device, name, url)
  })
}
