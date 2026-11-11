import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

// Same env file as the app, so specs can seed and clean up with the service role (Node 22+ built-in).
if (existsSync('.env.local')) process.loadEnvFile('.env.local')

const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:3000'

/**
 * End-to-end tests run against the dev Supabase project only (plan 15.10.2).
 * `pnpm build` first; the web server below is the production standalone server.
 * Set PW_CHANNEL=chrome to use the installed Google Chrome instead of Playwright's Chromium.
 */
export default defineConfig({
  testDir: 'tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    channel: process.env.PW_CHANNEL || undefined,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], channel: process.env.PW_CHANNEL || undefined }, testIgnore: /mobile\.spec\.ts/ },
    {
      name: 'mobile',
      // iPhone 14 size and touch, rendered by Chromium so no extra browser download is needed.
      use: { ...devices['iPhone 14'], browserName: 'chromium', channel: process.env.PW_CHANNEL || undefined },
      testMatch: /mobile\.spec\.ts/,
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: 'node .next/standalone/server.js',
        url: `${baseURL}/api/health`,
        reuseExistingServer: true,
        timeout: 60_000,
        env: { PORT: '3000', HOSTNAME: '127.0.0.1' },
      },
})
