// JavaScript budgets per page: fails when a page's first-load JavaScript (gzipped) is over its budget.
//
// Run after `next build` from web/:  node scripts/check-bundles.mjs [--strict] [--dir <web folder>]
//
// Next 16 writes .next/diagnostics/route-bundle-stats.json at build time: for every route, the JavaScript
// chunks the browser loads on the first visit (firstLoadChunkPaths). Each chunk is gzipped here (Node's default
// level, as the server sends it) and the sizes are added up, because every chunk is downloaded on its own.
// 1 KB = 1,024 bytes.
//
// Pages still on the first design are listed in TODO: they are measured and shown, but only fail the check
// once they leave the list (when their new version lands), or with --strict. A budgeted route that is not in
// the build at all fails, so a renamed page cannot slip out of its budget.
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

/** First-load JavaScript budgets, gzipped, in KB. */
export const BUDGETS_KB = {
  '/login': 140,
  '/': 175,
  '/leads/[id]': 185,
  '/leads': 190,
  '/pipeline': 190,
}

/** Routes not rebuilt yet: reported, never failing. Remove a route from here when its new version ships. */
export const TODO = new Set(['/', '/leads/[id]', '/leads', '/pipeline'])

const STATS_FILE = join('.next', 'diagnostics', 'route-bundle-stats.json')
const KB = 1024

function parseArgs(argv) {
  const args = { strict: false, dir: process.cwd() }
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--strict') args.strict = true
    else if (argv[i] === '--dir') args.dir = resolve(argv[++i] ?? '.')
    else throw new Error(`Unknown option ${argv[i]}. Use --strict or --dir <web folder>.`)
  }
  return args
}

/** Gzipped first-load bytes of every route in the build, largest first. */
export function measure(dir) {
  const statsPath = join(dir, STATS_FILE)
  if (!existsSync(statsPath)) {
    throw new Error(`${STATS_FILE} not found in ${dir}. Run \`next build\` first (Next 16 writes it at build time).`)
  }
  const stats = JSON.parse(readFileSync(statsPath, 'utf8'))
  if (!Array.isArray(stats)) throw new Error(`${STATS_FILE} is not a list of routes: has the Next.js format changed?`)
  const gzipped = new Map()
  const sizeOf = (chunk) => {
    if (!gzipped.has(chunk)) {
      const file = join(dir, chunk)
      if (!existsSync(file)) throw new Error(`${chunk} is listed for a route but missing from the build.`)
      gzipped.set(chunk, gzipSync(readFileSync(file)).length)
    }
    return gzipped.get(chunk)
  }
  return stats
    .filter((r) => r && typeof r.route === 'string' && Array.isArray(r.firstLoadChunkPaths))
    .map((r) => ({ route: r.route, bytes: [...new Set(r.firstLoadChunkPaths)].reduce((sum, chunk) => sum + sizeOf(chunk), 0) }))
    .sort((a, b) => b.bytes - a.bytes)
}

/** Every route with its size and verdict, and the failures (budgeted routes over budget or missing). */
export function check(routes, { budgets = BUDGETS_KB, todo = TODO, strict = false } = {}) {
  const byRoute = new Map(routes.map((r) => [r.route, r.bytes]))
  const failures = []
  const rows = routes.map(({ route, bytes }) => {
    const budget = budgets[route]
    if (budget === undefined) return { route, bytes, budget: null, status: 'no budget' }
    const over = bytes > budget * KB
    const pending = todo.has(route) && !strict
    if (over && !pending) failures.push(`${route} loads ${kb(bytes)} of JavaScript, over its ${budget} KB budget.`)
    return { route, bytes, budget, status: over ? (pending ? 'over (TODO)' : 'OVER') : 'ok' }
  })
  for (const route of Object.keys(budgets)) {
    if (byRoute.has(route)) continue
    if (todo.has(route) && !strict) rows.push({ route, bytes: null, budget: budgets[route], status: 'missing (TODO)' })
    else failures.push(`${route} has a budget but is not in the build. Rename or remove it in scripts/check-bundles.mjs.`)
  }
  return { rows, failures }
}

const kb = (bytes) => `${(bytes / KB).toFixed(1)} KB`

function report(rows) {
  const width = Math.max(...rows.map((r) => r.route.length), 5)
  const lines = [`${'Route'.padEnd(width)}  ${'First load (gzip)'.padStart(17)}  ${'Budget'.padStart(8)}  Status`]
  for (const r of rows) {
    lines.push(
      `${r.route.padEnd(width)}  ${(r.bytes === null ? '-' : kb(r.bytes)).padStart(17)}  ${(r.budget === null ? '-' : `${r.budget} KB`).padStart(8)}  ${r.status}`,
    )
  }
  return lines.join('\n')
}

function main() {
  let args
  try {
    args = parseArgs(process.argv.slice(2))
    const { rows, failures } = check(measure(args.dir), { strict: args.strict })
    console.log(report(rows))
    if (failures.length) {
      console.error(`\nJavaScript budget check failed:\n${failures.map((f) => `- ${f}`).join('\n')}`)
      process.exit(1)
    }
    const pending = rows.filter((r) => r.status.endsWith('(TODO)')).length
    console.log(`\nJavaScript budgets: ok${pending ? ` (${pending} not rebuilt yet, listed in TODO)` : ''}.`)
  } catch (e) {
    console.error(e instanceof Error ? e.message : e)
    process.exit(1)
  }
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname)) main()
