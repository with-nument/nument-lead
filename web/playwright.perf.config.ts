import { existsSync } from 'node:fs'
import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

// Page timings: TTFB, content ready, full load and Supabase calls per page, signed in as the temporary
// admin from the e2e fixtures (created and deleted around the run, never a real user).
// `pnpm build` first, then: PERF_OUT=/abs/path/result.json pnpm exec playwright test -c playwright.perf.config.ts
// PERF_SERVER=/abs/path/server.js measures another standalone build (for example the one before a change).
if (existsSync('.env.local')) process.loadEnvFile('.env.local')

const port = process.env.PERF_PORT ?? '3100'
export const PERF_LOG_FILE = path.resolve(process.env.PERF_LOG_FILE ?? 'test-results/perf-log.jsonl')
process.env.PERF_LOG_FILE = PERF_LOG_FILE

export default defineConfig({
  testDir: 'tests/perf',
  workers: 1,
  timeout: 600_000,
  reporter: [['list']],
  globalSetup: './tests/e2e/global-setup.ts',
  globalTeardown: './tests/e2e/global-teardown.ts',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
    channel: process.env.PW_CHANNEL || undefined,
  },
  webServer: {
    command: `node ${process.env.PERF_SERVER ?? '.next/standalone/server.js'}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { PORT: port, HOSTNAME: '127.0.0.1', PERF_LOG: '1', PERF_LOG_FILE },
  },
})
