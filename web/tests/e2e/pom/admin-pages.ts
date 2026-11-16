import { expect, type Locator, type Page } from '@playwright/test'

// Page objects for the new design's Settings, Engine and Insights pages (src/app/(v2)/v2/{settings,engine,insights}).
// They work at the normal URLs with the new design switched on (useNewDesign). Every section is a region named
// by its heading, so a test finds it the way a screen reader would.

class V2Page {
  readonly main: Locator
  constructor(readonly page: Page) {
    this.main = page.locator('main#main')
  }

  heading(name: string) {
    return this.main.getByRole('heading', { level: 1, name })
  }

  section(title: string) {
    return this.main.getByRole('region', { name: title, exact: true })
  }

  /** The sheet open now (a dialog). */
  get sheet() {
    return this.page.getByRole('dialog')
  }

  toast(text: string | RegExp) {
    return this.page.locator('[aria-live="polite"]').getByText(text)
  }
}

export class SettingsPage extends V2Page {
  async goto() {
    await this.page.goto('/settings')
    await expect(this.heading('Settings')).toBeVisible()
  }

  get profile() {
    return this.section('Profile')
  }
  get team() {
    return this.section('Team')
  }
  get mailbox() {
    return this.section('Mailbox')
  }
  get sending() {
    return this.section('Sending')
  }
  get recipients() {
    return this.section('Email recipients')
  }
  get doNotContact() {
    return this.section('Do not contact')
  }
  get design() {
    return this.section('Design')
  }

  /** Pause all sending (admins). */
  get pauseSwitch() {
    return this.sending.getByRole('switch', { name: 'Pause all sending' })
  }

  get connectGmail() {
    return this.mailbox.getByRole('button', { name: 'Connect Gmail' })
  }

  async rename(name: string) {
    await this.profile.getByRole('button', { name: /^Name/ }).click()
    await this.sheet.getByLabel('Full name').fill(name)
    await this.sheet.getByRole('button', { name: 'Save name' }).click()
    await expect(this.sheet).toBeHidden()
  }

  async invite(email: string, fullName: string, role: 'Admin' | 'Caller' | 'Viewer' = 'Caller') {
    await this.team.getByRole('button', { name: 'Invite' }).click()
    await this.sheet.getByLabel('Email').fill(email)
    await this.sheet.getByLabel('Full name').fill(fullName)
    await this.sheet.getByLabel('Role').selectOption({ label: role })
    await this.sheet.getByRole('button', { name: 'Create account' }).click()
    // The temporary password is shown once, in its own sheet.
    const password = (await this.sheet.locator('code').textContent())?.trim() ?? ''
    return password
  }

  async addDoNotContact(kind: 'Email' | 'Phone' | 'Website', value: string) {
    await this.doNotContact.getByRole('button', { name: 'Add' }).click()
    await this.sheet.getByRole('radio', { name: kind }).click()
    await this.sheet.getByLabel(kind).fill(value)
    await this.sheet.getByRole('button', { name: 'Add' }).click()
    await expect(this.sheet).toBeHidden()
  }

  /** Removes an entry; an inline Undo row takes its place for 30 seconds. */
  async removeDoNotContact(label: string) {
    await this.doNotContact.getByRole('button', { name: `Remove ${label} from Do not contact` }).click()
    return this.doNotContact.getByRole('status').getByRole('button', { name: 'Undo' })
  }

  async useClassicDesign() {
    await Promise.all([this.page.waitForEvent('load'), this.design.getByRole('switch', { name: 'Use the new design' }).click()])
  }
}

export class EnginePage extends V2Page {
  async goto() {
    await this.page.goto('/engine')
    await expect(this.heading('Engine')).toBeVisible()
  }

  get runNow() {
    return this.page.getByRole('button', { name: 'Run now' })
  }
  get runs() {
    return this.section('Runs')
  }
  get segments() {
    return this.section('Segments')
  }
  get posts() {
    return this.section('Posts')
  }
  get budget() {
    return this.section('Budget')
  }
  get sources() {
    return this.section('Sources')
  }
  get queue() {
    return this.section('Search queue')
  }

  segmentSwitch(label: string) {
    return this.segments.getByRole('switch', { name: `${label} on or off` })
  }

  sourceSwitch(source: string) {
    return this.sources.getByRole('switch', { name: `${source} on or off` })
  }

  async pastePost(text: string, url = '') {
    await this.posts.getByRole('button', { name: 'Paste a post' }).click()
    await this.sheet.getByLabel('Post text').fill(text)
    if (url) await this.sheet.getByLabel('Link').fill(url)
    await this.sheet.getByRole('button', { name: 'Add post' }).click()
    await expect(this.sheet).toBeHidden()
  }

  /** Opens Run now and starts a dry run of the given kind. */
  async dryRun(kind: 'Morning' | 'Night' | 'Sheet sync') {
    await this.runNow.click()
    await this.sheet.getByRole('radio', { name: kind }).click()
    await expect(this.sheet.getByRole('switch', { name: 'Dry run' })).toHaveAttribute('aria-checked', 'true')
    await this.sheet.getByRole('button', { name: 'Start dry run' }).click()
  }
}

export class InsightsPage extends V2Page {
  async goto(query = '') {
    await this.page.goto(`/insights${query}`)
    await expect(this.heading('Insights')).toBeVisible()
  }

  get period() {
    return this.main.getByRole('radiogroup', { name: 'Period' })
  }
  get funnel() {
    return this.section('Funnel')
  }
  get bySegment() {
    return this.section('Contacted by segment')
  }
  get whatWorks() {
    return this.section('What works')
  }
  get quality() {
    return this.section('Lead quality')
  }
  /** Admins only. */
  get cost() {
    return this.section('Cost')
  }

  async choosePeriod(label: '7 days' | '30 days' | '90 days') {
    await this.period.getByRole('radio', { name: label }).click()
    await this.page.waitForURL(label === '30 days' ? /\/insights(\?(?!.*days=).*)?$/ : new RegExp(`days=${label.split(' ')[0]}`))
  }

  async groupBy(label: string) {
    await this.whatWorks.getByLabel('Group by').selectOption({ label: `By ${label.toLowerCase()}` })
  }
}
