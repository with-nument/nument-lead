import { expect, type Locator, type Page } from '@playwright/test'

/**
 * The sign-in page (src/app/(auth)/login). Every locator uses the accessible names the page promises:
 * heading 'Sign in' (it reads 'Sign in to Nument Lead desk'), fields 'Email' and 'Password'.
 * Two steps, both in the browser: 'Continue with email' shows the password field and the button
 * becomes 'Sign in'; only that second press goes to the server.
 */
export class LoginPage {
  readonly heading: Locator
  readonly email: Locator
  readonly password: Locator
  readonly showPassword: Locator
  readonly continue: Locator
  readonly submit: Locator
  readonly forgotPassword: Locator
  readonly noSignUp: Locator
  readonly error: Locator

  constructor(readonly page: Page) {
    this.heading = page.getByRole('heading', { name: 'Sign in' })
    this.email = page.getByLabel('Email', { exact: true })
    this.password = page.getByLabel('Password', { exact: true })
    this.showPassword = page.getByRole('button', { name: /^(Show|Hide) password$/ })
    this.continue = page.getByRole('button', { name: 'Continue with email' })
    this.submit = page.getByRole('button', { name: 'Sign in', exact: true })
    this.forgotPassword = page.getByRole('link', { name: 'Forgot password?' })
    this.noSignUp = page.getByText('There is no public sign-up.')
    this.error = page.getByRole('alert').filter({ hasText: /\S/ })
  }

  /** Opens the page, optionally with the address to return to after signing in. */
  async goto(next?: string) {
    await this.page.goto(next ? `/login?next=${encodeURIComponent(next)}` : '/login')
    await expect(this.heading).toBeVisible()
  }

  /** Step one: the email, then 'Continue with email' (the button is disabled until the page is interactive). */
  async continueWith(email: string) {
    await this.email.fill(email)
    await expect(this.continue).toBeEnabled()
    await this.continue.click()
    await expect(this.submit).toBeVisible()
  }

  /** Both steps, up to the 'Sign in' press. */
  async fill(email: string, password: string) {
    await this.continueWith(email)
    await this.password.fill(password)
  }

  /** Signs in and waits until the app has taken over from the login page. */
  async signIn(email: string, password: string) {
    await this.fill(email, password)
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
