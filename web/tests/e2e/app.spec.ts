import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { assertFixtureLead, readRun, serviceClient, type Run } from './fixtures'
import { signIn, userClient } from './support'

// Signed-in flows with the temporary admin and caller from globalSetup. Every lead a test changes is
// a fixture, checked by the guard first; globalTeardown deletes all of it.
test.describe.configure({ mode: 'serial' })

// Read after globalSetup has written it (test files are also loaded for listing).
let run: Run
test.beforeAll(() => {
  run = readRun()
})

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
}

test('Today: Mark sent moves the lead to Contacted and Undo restores it', async ({ page }) => {
  await assertFixtureLead(run.leadIds.new1)
  await signIn(page, run.admin.email, run.admin.password)
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
  const name = run.names.new1
  const row = page.getByRole('listitem').filter({ has: page.getByRole('link', { name }) })
  await expect(row).toBeVisible()
  await axe(page)

  await row.getByRole('button', { name: `More actions for ${name}` }).click()
  await page.getByRole('menuitem', { name: 'Mark sent' }).click()
  await expect(page.getByText('Marked as contacted')).toBeVisible()
  await expect(row).toHaveCount(0)

  const db = serviceClient()
  const { data: lead } = await db.from('leads').select('stage, wa_at').eq('id', run.leadIds.new1).single()
  expect(lead?.stage).toBe('contacted')
  expect(lead?.wa_at).toBeTruthy()
  const { data: sent } = await db.from('activities').select('source').eq('lead_id', run.leadIds.new1).eq('type', 'sent')
  expect(sent).toEqual([{ source: 'app' }])
  const { data: changes } = await db.from('activities').select('id').eq('lead_id', run.leadIds.new1).eq('type', 'stage_change')
  expect(changes?.length).toBe(1) // written once, by the database trigger

  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(page.getByText('Undone')).toBeVisible()
  await expect.poll(async () => (await db.from('leads').select('stage, wa_at').eq('id', run.leadIds.new1).single()).data).toEqual({ stage: 'new', wa_at: null })
})

test('Lead page: change stage, see it in the timeline and on the Pipeline', async ({ page }) => {
  await assertFixtureLead(run.leadIds.contacted)
  await signIn(page, run.admin.email, run.admin.password)
  await page.goto(`/leads/${run.leadIds.contacted}`)
  await expect(page.getByRole('heading', { name: run.names.contacted })).toBeVisible()
  await axe(page)
  await page.getByLabel('Stage').selectOption('talking')
  await expect(page.getByText('Stage updated')).toBeVisible()
  await expect(page.getByText(/moved the stage from Contacted to Talking/)).toBeVisible()

  await page.goto('/pipeline')
  const column = page.getByRole('listitem', { name: /^Talking,/ })
  await expect(column.getByRole('link', { name: run.names.contacted })).toBeVisible()
})

test('Message lint blocks saving until the problem is fixed', async ({ page }) => {
  await assertFixtureLead(run.leadIds.new2)
  await signIn(page, run.admin.email, run.admin.password)
  await page.goto(`/leads/${run.leadIds.new2}`)
  const box = page.getByLabel('First message')
  const original = await box.inputValue()
  await box.fill(original.replace('busy.', 'busy — always.'))
  await expect(page.getByText('Contains a dash')).toBeVisible()
  const card = page.getByRole('region', { name: 'Message' })
  await expect(card.getByRole('button', { name: 'Save' })).toBeDisabled()
  await box.fill(original)
  await expect(card.getByText(/Looks good/).first()).toBeVisible()
})

test('Admin sees the deal value', async ({ page }) => {
  await signIn(page, run.admin.email, run.admin.password)
  await page.goto(`/leads/${run.leadIds.proposal}`)
  await expect(page.getByLabel('Deal value (₹)')).toHaveValue('150000')
  await expect(page.getByText('₹1,50,000').first()).toBeVisible()
})

test('Admin creates a user; a new caller must change the password and never sees money', async ({ page, browser }) => {
  const email = `e2e-created-${run.runId}@example.com`
  await signIn(page, run.admin.email, run.admin.password)
  await page.goto('/settings/users')
  await page.getByRole('button', { name: 'Create user' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Full name').fill('E2E Created Caller')
  await dialog.getByLabel('Email').fill(email)
  await dialog.getByLabel('Role', { exact: true }).selectOption('caller')
  await dialog.getByRole('button', { name: 'Create user' }).click()
  const temp = (await page.getByTestId('temp-password').textContent())?.trim() ?? ''
  expect(temp).toHaveLength(16)
  const { data: list } = await serviceClient().auth.admin.listUsers({ page: 1, perPage: 1000 })
  const created = list.users.find((u) => u.email === email)
  expect(created?.app_metadata?.must_change_password).toBe(true)
  expect(created?.user_metadata?.must_change_password).toBeUndefined()

  const ctx = await browser.newContext()
  const caller = await ctx.newPage()
  await signIn(caller, email, temp)
  await expect(caller).toHaveURL(/\/settings\?change_password=1$/)

  // The flag cannot be cleared from the browser: a user can only write user_metadata.
  const self = await userClient(email, temp)
  await self.auth.updateUser({ data: { must_change_password: false } })
  await caller.goto('/leads')
  await expect(caller).toHaveURL(/\/settings\?change_password=1$/)

  const fresh = `Calm-Indigo-${run.runId}!9`
  await caller.getByLabel('New password').fill(fresh)
  await caller.getByLabel('Type it again').fill(fresh)
  await caller.getByRole('button', { name: 'Set my password' }).click()
  await expect(caller.getByRole('heading', { name: 'Today' })).toBeVisible()

  await caller.goto(`/leads/${run.leadIds.proposal}`)
  await expect(caller.getByRole('heading', { name: run.names.proposal })).toBeVisible()
  await expect(caller.getByText('Deal value')).toHaveCount(0)
  await expect(caller.getByText('₹1,50,000')).toHaveCount(0)
  await caller.goto('/engine')
  await expect(caller).toHaveURL(/\/$/)
  const csv = await caller.request.get('/leads/export')
  expect(csv.status()).toBe(200)
  expect((await csv.text()).split('\r\n')[0]).not.toContain('Deal value')

  const db = await userClient(email, fresh)
  const direct = await db.from('leads').select('deal_value_inr').limit(1)
  expect(direct.error?.code).toBe('42501')
  const adminView = await db.from('v_leads_admin').select('id, deal_value_inr')
  expect(adminView.data ?? []).toEqual([])
  await ctx.close()
})
