import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { allowUserCreation, cleanup, creds, hasAdmin, seed, serviceClient, signIn, userClient, type Seeded } from './support'

// Needs a dev test admin without a temporary password (E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD).
// Seeds five clearly marked test leads and removes them afterwards.
test.skip(!hasAdmin, 'Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD (a dev test admin) to run.')
test.describe.configure({ mode: 'serial' })

let s: Seeded | undefined
test.beforeAll(async () => {
  s = await seed()
})
test.afterAll(async () => {
  await cleanup(s)
})

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([])
}

test('Today: Mark sent moves the lead to Contacted and Undo restores it', async ({ page }) => {
  await signIn(page, creds.admin.email, creds.admin.password)
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
  const name = `E2E Test Clinic 1 ${s!.runId}`
  const row = page.getByRole('listitem').filter({ has: page.getByRole('link', { name }) })
  await expect(row).toBeVisible()
  await axe(page)

  await row.getByRole('button', { name: `More actions for ${name}` }).click()
  await page.getByRole('menuitem', { name: 'Mark sent' }).click()
  await expect(page.getByText('Marked as contacted')).toBeVisible()
  await expect(row).toHaveCount(0)

  const db = serviceClient()
  const { data: lead } = await db.from('leads').select('stage, wa_at').eq('id', s!.leadIds.new1).single()
  expect(lead?.stage).toBe('contacted')
  expect(lead?.wa_at).toBeTruthy()
  const { data: sent } = await db.from('activities').select('source').eq('lead_id', s!.leadIds.new1).eq('type', 'sent')
  expect(sent).toEqual([{ source: 'app' }])
  const { data: changes } = await db.from('activities').select('id').eq('lead_id', s!.leadIds.new1).eq('type', 'stage_change')
  expect(changes?.length).toBe(1) // written once, by the database trigger

  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(page.getByText('Undone')).toBeVisible()
  await expect.poll(async () => (await db.from('leads').select('stage, wa_at').eq('id', s!.leadIds.new1).single()).data).toEqual({ stage: 'new', wa_at: null })
})

test('Lead page: change stage, see it in the timeline and on the Pipeline', async ({ page }) => {
  await signIn(page, creds.admin.email, creds.admin.password)
  await page.goto(`/leads/${s!.leadIds.contacted}`)
  await expect(page.getByRole('heading', { name: `E2E Test Clinic 3 ${s!.runId}` })).toBeVisible()
  await axe(page)
  await page.getByLabel('Stage').selectOption('talking')
  await expect(page.getByText('Stage updated')).toBeVisible()
  await expect(page.getByText(/moved the stage from Contacted to Talking/)).toBeVisible()

  await page.goto('/pipeline')
  const column = page.getByRole('listitem', { name: /^Talking,/ })
  await expect(column.getByRole('link', { name: `E2E Test Clinic 3 ${s!.runId}` })).toBeVisible()
})

test('Message lint blocks saving until the problem is fixed', async ({ page }) => {
  await signIn(page, creds.admin.email, creds.admin.password)
  await page.goto(`/leads/${s!.leadIds.new2}`)
  const box = page.getByLabel('First message')
  const original = await box.inputValue()
  await box.fill(original.replace('busy.', 'busy — always.'))
  await expect(page.getByText('Contains a dash')).toBeVisible()
  const card = page.getByRole('region', { name: 'Message' })
  await expect(card.getByRole('button', { name: 'Save' })).toBeDisabled()
  await box.fill(original)
  await expect(page.getByText(/Looks good/).first()).toBeVisible()
})

test('Admin sees and edits the deal value', async ({ page }) => {
  await signIn(page, creds.admin.email, creds.admin.password)
  await page.goto(`/leads/${s!.leadIds.proposal}`)
  await expect(page.getByLabel('Deal value (₹)')).toHaveValue('150000')
})

test('A caller never sees money (temporary caller, created and deleted)', async ({ page, browser }) => {
  test.skip(!allowUserCreation, 'Set E2E_ALLOW_USER_CREATION=1 to create and delete a temporary caller.')
  const email = `e2e-caller-${s!.runId}@example.com`
  let callerId: string | undefined
  try {
    await signIn(page, creds.admin.email, creds.admin.password)
    await page.goto('/settings/users')
    await page.getByRole('button', { name: 'Create user' }).click()
    await page.getByLabel('Full name').fill('E2E Caller')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Role').selectOption('caller')
    await page.getByRole('button', { name: 'Create user' }).last().click()
    const temp = (await page.getByTestId('temp-password').textContent())?.trim() ?? ''
    expect(temp).toHaveLength(16)
    const { data: list } = await serviceClient().auth.admin.listUsers({ page: 1, perPage: 200 })
    callerId = list.users.find((u) => u.email === email)?.id

    const ctx = await browser.newContext()
    const caller = await ctx.newPage()
    await signIn(caller, email, temp)
    await expect(caller).toHaveURL(/\/settings\?change_password=1$/)
    const fresh = `Calm-Indigo-${s!.runId}!9`
    await caller.getByLabel('New password').fill(fresh)
    await caller.getByLabel('Type it again').fill(fresh)
    await caller.getByRole('button', { name: 'Set my password' }).click()
    await expect(caller.getByRole('heading', { name: 'Today' })).toBeVisible()

    await caller.goto(`/leads/${s!.leadIds.proposal}`)
    await expect(caller.getByRole('heading', { name: `E2E Test Clinic 5 ${s!.runId}` })).toBeVisible()
    await expect(caller.getByText('Deal value')).toHaveCount(0)
    await caller.goto('/engine')
    await expect(caller).toHaveURL(/\/$/)
    const csv = await caller.request.get('/leads/export')
    expect(csv.status()).toBe(200)
    expect((await csv.text()).split('\r\n')[0]).not.toContain('Deal value')

    const db = await userClient(email, fresh)
    const direct = await db.from('leads').select('deal_value_inr').limit(1)
    expect(direct.error).not.toBeNull()
    const adminView = await db.from('v_leads_admin').select('id, deal_value_inr')
    expect(adminView.data ?? []).toEqual([])
    await ctx.close()
  } finally {
    if (callerId) await serviceClient().auth.admin.deleteUser(callerId)
  }
})
