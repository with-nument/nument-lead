import { expect, type Locator, type Page } from '@playwright/test'

/**
 * The sign-in page (src/app/(auth)/login). Every locator uses the accessible names the page promises:
 * heading 'Sign in', fields 'Email' and 'Password', button 'Sign in'.
 */
export class LoginPage {
  readonly heading: Locator
  readonly email: Locator
  readonly password: Locator
  readonly showPassword: Locator
  readonly submit: Locator
  readonly forgotPassword: Locator
  readonly noSignUp: Locator
  readonly error: Locator

  constructor(readonly page: Page) {
    this.heading = page.getByRole('heading', { name: 'Sign in' })
    this.email = page.getByLabel('Email', { exact: true })
    this.password = page.getByLabel('Password', { exact: true })
    this.showPassword = page.getByRole('button', { name: /^(Show|Hide) password$/ })
    this.submit = page.getByRole('button', { name: 'Sign in' })
    this.forgotPassword = page.getByRole('link', { name: 'Forgot password?' })
    this.noSignUp = page.getByText('There is no public sign-up.')
    this.error = page.getByRole('alert').filter({ hasText: /\S/ })
  }

  /** Opens the page, optionally with the address to return to after signing in. */
  async goto(next?: string) {
    await this.page.goto(next ? `/login?next=${encodeURIComponent(next)}` : '/login')
    await expect(this.heading).toBeVisible()
  }

  async fill(email: string, password: string) {
    await this.email.fill(email)
    await this.password.fill(password)
  }

  /** Signs in and waits until the app has taken over from the login page. */
  async signIn(email: string, password: string) {
    await this.fill(email, password)
    // The button is disabled until the page is interactive.
    await expect(this.submit).toBeEnabled()
    await this.submit.click()
    await this.page.waitForURL((url) => !url.pathname.startsWith('/login'))
  }
}

/** The reset page (src/app/(auth)/reset-password): one Email field and 'Send reset link'. */
export class ResetPasswordPage {
  readonly heading: Locator
  readonly email: Locator
  readonly submit: Locator
  readonly sent: Locator

  constructor(readonly page: Page) {
    this.heading = page.getByRole('heading', { name: 'Reset password' })
    this.email = page.getByLabel('Email', { exact: true })
    this.submit = page.getByRole('button', { name: 'Send reset link' })
    this.sent = page.getByRole('status').filter({ hasText: 'If this email has an account' })
  }

  async goto() {
    await this.page.goto('/reset-password')
    await expect(this.heading).toBeVisible()
  }

  async request(email: string) {
    await this.email.fill(email)
    await expect(this.submit).toBeEnabled()
    await this.submit.click()
    await expect(this.sent).toBeVisible()
  }
}
