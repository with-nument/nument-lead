import { expect, type Locator, type Page } from '@playwright/test'

export const PRIMARY = ['Today', 'Inbox', 'Calls', 'Deals', 'Leads'] as const
export const SECONDARY = ['Insights', 'Engine', 'Settings'] as const
export type Place = (typeof PRIMARY)[number] | (typeof SECONDARY)[number]

/**
 * The new design's shell (src/components/shell2): a sidebar from 1024 px, a tab bar below it. Both are
 * the navigation named 'Main'; only one is ever shown. Secondary places live in the sidebar on laptops
 * and in the account sheet on phones.
 */
export class Shell {
  readonly nav: Locator
  readonly main: Locator
  readonly account: Locator

  constructor(readonly page: Page) {
    this.nav = page.getByRole('navigation', { name: 'Main' })
    this.main = page.locator('main#main')
    this.account = page.getByRole('button', { name: 'Account' })
  }

  /** True when the tab bar (not the sidebar) is the navigation on screen. */
  async isCompact() {
    const width = this.page.viewportSize()?.width ?? 1280
    return width < 1024
  }

  link(place: Place) {
    return this.nav.getByRole('link', { name: place, exact: true })
  }

  /** The page title: the large title, the one level-1 heading on a v2 page. */
  title(text: string) {
    return this.main.getByRole('heading', { level: 1, name: text })
  }

  /** Goes to a place the way a person would: tab bar or sidebar, or the account sheet for secondary places on phones. */
  async go(place: Place) {
    if ((SECONDARY as readonly string[]).includes(place) && (await this.isCompact())) {
      await this.openAccount()
      await this.page.getByRole('dialog').getByRole('link', { name: place, exact: true }).click()
      return
    }
    await this.link(place).click()
  }

  async expectCurrent(place: Place) {
    await expect(this.link(place)).toHaveAttribute('aria-current', 'page')
  }

  /** Opens the account menu (laptop) or account sheet (phone). */
  async openAccount() {
    await this.account.filter({ visible: true }).first().click()
  }

  /** Account > Use the classic design: clears the cookie and reloads into the current design. */
  async useClassicDesign() {
    await this.openAccount()
    const item = (await this.isCompact())
      ? this.page.getByRole('dialog').getByRole('button', { name: 'Use the classic design' })
      : this.page.getByRole('menuitem', { name: 'Use the classic design' })
    await Promise.all([this.page.waitForEvent('load'), item.click()])
  }

  async signOut() {
    await this.openAccount()
    const item = (await this.isCompact())
      ? this.page.getByRole('dialog').getByRole('button', { name: 'Sign out' })
      : this.page.getByRole('menuitem', { name: 'Sign out' })
    await item.click()
    await this.page.waitForURL(/\/login/)
  }
}
