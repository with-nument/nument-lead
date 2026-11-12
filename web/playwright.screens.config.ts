import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

// Visual review: screenshots of every page as admin and caller, desktop and phone, using the same
// temporary users and fixture leads as the e2e suite (created and deleted around the run).
// Run with: SHOTS_DIR=/abs/path pnpm exec playwright test -c playwright.screens.config.ts
if (existsSync('.env.local')) process.loadEnvFile('.env.local')

export default defineConfig({
  testDir: 'tests/screens',
  workers: 1,
  timeout: 180_000,
  reporter: [['list']],
  globalSetup: './tests/e2e/global-setup.ts',
  globalTeardown: './tests/e2e/global-teardown.ts',
  use: { baseURL: 'http://127.0.0.1:3000', channel: process.env.PW_CHANNEL || undefined },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, channel: process.env.PW_CHANNEL || undefined } },
    { name: 'phone', use: { ...devices['iPhone 14'], browserName: 'chromium', channel: process.env.PW_CHANNEL || undefined } },
  ],
  webServer: {
    command: 'node .next/standalone/server.js',
    url: 'http://127.0.0.1:3000/api/health',
    reuseExistingServer: true,
    timeout: 60_000,
    env: { PORT: '3000', HOSTNAME: '127.0.0.1' },
  },
})
