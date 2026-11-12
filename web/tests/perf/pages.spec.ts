import { readFileSync, writeFileSync, existsSync, truncateSync } from 'node:fs'
import { test, type Page } from '@playwright/test'
import { readRun } from '../e2e/fixtures'
import { signIn } from '../e2e/support'

// Measures every signed-in page as the temporary e2e admin. For each page: a few full loads (TTFB,
// content ready = no skeleton left, load event) and the Supabase calls the server made meanwhile,
// read from the PERF_LOG_FILE the server writes (src/lib/perf.ts). Then sidebar clicks, to check that
// moving between pages is client-side (no new document) and how long the new page takes to show.

type Entry = { at: number; ms: number; source: string; kind: string; name: string; status?: number }
const LOG = process.env.PERF_LOG_FILE!
const RUNS = Number(process.env.PERF_RUNS ?? 3)

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b)
  return s.length ? s[Math.floor(s.length / 2)]! : NaN
}
const entries = (): Entry[] =>
  existsSync(LOG)
    ? readFileSync(LOG, 'utf8')
        .split('\n')
        .filter(Boolean)
        .map((l) => JSON.parse(l) as Entry)
    : []

async function contentReady(page: Page) {
  await page.waitForFunction(() => !document.querySelector('[aria-busy]') && document.querySelector('main h1, main h2, main [data-tour]'), null, { timeout: 30_000 })
}

/** Calls the server made in [from, to], split by where they came from. */
function calls(from: number, to: number) {
  const list = entries().filter((e) => e.at >= from && e.at <= to)
  const net = list.filter((e) => e.kind !== 'local')
  const server = net.filter((e) => e.source !== 'proxy')
  const wall = server.length ? Math.max(...server.map((e) => e.at + e.ms)) - Math.min(...server.map((e) => e.at)) : 0
  return {
    total: net.length,
    rest: net.filter((e) => e.kind === 'rest').length,
    auth: net.filter((e) => e.kind === 'auth').length,
    storage: net.filter((e) => e.kind === 'storage').length,
    getUser: net.filter((e) => e.kind === 'auth' && e.name.endsWith(' user')).length,
    proxyRequests: list.filter((e) => e.source === 'proxy' && e.name.startsWith('getClaims')).length,
    serverWallMs: Math.round(wall),
    names: net.map((e) => `${e.source}:${e.name.split('?')[0]}`),
  }
}

test('page timings', async ({ page }) => {
  const run = readRun()
  if (existsSync(LOG)) truncateSync(LOG, 0)
  await signIn(page, run.admin.email, run.admin.password)
  await contentReady(page)

  const pages: [string, string][] = [
    ['Today', '/'],
    ['Leads', '/leads'],
    ['Lead', `/leads/${run.leadIds.talking}`],
    ['Pipeline', '/pipeline'],
    ['Insights', '/insights'],
    ['Engine', '/engine'],
    ['Inbox', '/inbox'],
    ['Settings', '/settings'],
    ['Users', '/settings/users'],
    ['Do not contact', '/settings/suppression'],
    ['Email', '/settings/email'],
  ]

  const results: Record<string, unknown>[] = []
  for (const [label, url] of pages) {
    // One warm-up load so every page is measured with a warm server and warm caches.
    await page.goto(url)
    await contentReady(page)
    const ttfb: number[] = []
    const ready: number[] = []
    const load: number[] = []
    let q: ReturnType<typeof calls> | null = null
    let size = {}
    for (let i = 0; i < RUNS; i++) {
      await page.waitForTimeout(400)
      const from = Date.now()
      await page.goto(url, { waitUntil: 'commit' })
      await contentReady(page)
      const readyAt = await page.evaluate(() => performance.now())
      await page.waitForLoadState('load')
      const nav = await page.evaluate(() => {
        const n = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
        const js = (performance.getEntriesByType('resource') as PerformanceResourceTiming[]).filter((r) => r.initiatorType === 'script' || r.name.endsWith('.js'))
        return {
          ttfb: n.responseStart,
          load: n.loadEventEnd,
          jsKb: Math.round(js.reduce((s, r) => s + r.decodedBodySize, 0) / 1024),
          jsWireKb: Math.round(js.reduce((s, r) => s + r.transferSize, 0) / 1024),
          htmlKb: Math.round(n.decodedBodySize / 1024),
        }
      })
      size = { jsKb: nav.jsKb, jsWireKb: nav.jsWireKb, htmlKb: nav.htmlKb }
      ttfb.push(nav.ttfb)
      ready.push(readyAt)
      load.push(Math.max(nav.load, readyAt))
      await page.waitForTimeout(300)
      q = calls(from, Date.now())
    }
    results.push({
      page: label,
      ttfbMs: Math.round(median(ttfb)),
      contentMs: Math.round(median(ready)),
      loadMs: Math.round(median(load)),
      ...size,
      ...q,
    })
  }

  // Client-side navigation through the sidebar.
  await page.goto('/')
  await contentReady(page)
  let documents = 0
  page.on('request', (r) => {
    if (r.resourceType() === 'document') documents++
  })
  const navs: Record<string, unknown>[] = []
  for (const [label, url] of pages.filter(([, u]) => ['/leads', '/pipeline', '/insights', '/engine', '/inbox', '/settings', '/'].includes(u))) {
    await page.waitForTimeout(1500) // let prefetches land, as a person would take a moment
    const before = documents
    const from = Date.now()
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: label, exact: true }).click()
    await page.waitForURL((u) => u.pathname === url)
    const urlMs = Date.now() - from
    await contentReady(page)
    navs.push({ to: label, urlMs, contentMs: Date.now() - from, documentLoads: documents - before, ...calls(from, Date.now()) })
  }

  const out = { at: new Date().toISOString(), runs: RUNS, pages: results, navigation: navs }
  if (process.env.PERF_OUT) writeFileSync(process.env.PERF_OUT, JSON.stringify(out, null, 2))
  const brief = (r: Record<string, unknown>) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== 'names'))
  console.table(results.map(brief))
  console.table(navs.map(brief))
})
