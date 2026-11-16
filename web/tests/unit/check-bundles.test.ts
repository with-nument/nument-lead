import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomBytes } from 'node:crypto'
import { afterEach, describe, expect, it } from 'vitest'

// scripts/check-bundles.mjs against a made-up build: route-bundle-stats.json as Next 16 writes it, and chunks of
// random bytes (random data does not compress, so a chunk's gzipped size is a little over its length).
const SCRIPT = fileURLToPath(new URL('../../scripts/check-bundles.mjs', import.meta.url))
const KB = 1024
const dirs: string[] = []

function fakeBuild(routes: Record<string, number[]>) {
  const dir = mkdtempSync(join(tmpdir(), 'bundles-'))
  dirs.push(dir)
  mkdirSync(join(dir, '.next', 'diagnostics'), { recursive: true })
  mkdirSync(join(dir, '.next', 'static', 'chunks'), { recursive: true })
  const stats = Object.entries(routes).map(([route, sizes]) => ({
    route,
    firstLoadChunkPaths: sizes.map((kb, i) => {
      const path = `.next/static/chunks/${route.replace(/\W/g, '_')}-${i}.js`
      writeFileSync(join(dir, path), randomBytes(kb * KB))
      return path
    }),
    firstLoadUncompressedJsBytes: sizes.reduce((a, b) => a + b, 0) * KB,
  }))
  writeFileSync(join(dir, '.next', 'diagnostics', 'route-bundle-stats.json'), JSON.stringify(stats))
  return dir
}

const run = (dir: string, ...args: string[]) => spawnSync(process.execPath, [SCRIPT, '--dir', dir, ...args], { encoding: 'utf8' })

afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe('check-bundles', () => {
  const v2 = ['/v2', '/v2/calls', '/v2/deals', '/v2/inbox', '/v2/leads', '/v2/insights', '/v2/settings', '/v2/engine']
  const underBudget = {
    '/login': [100],
    '/': [120],
    '/leads/[id]': [150],
    '/leads': [160],
    '/pipeline': [160],
    '/settings': [400],
    ...Object.fromEntries(v2.map((r) => [r, [150]])),
  }

  it('passes when every budgeted page is under its budget, and lists every route', () => {
    const out = run(fakeBuild(underBudget), '--strict')
    expect(out.status).toBe(0)
    expect(out.stdout).toMatch(/\/settings\s+\d+\.\d KB\s+-\s+no budget/)
    expect(out.stdout).toMatch(/\/login\s+10\d\.\d KB\s+140 KB\s+ok/)
  })

  it('adds up every chunk of a page', () => {
    const out = run(fakeBuild({ ...underBudget, '/login': [80, 70] }), '--strict')
    expect(out.status).toBe(1)
    expect(out.stderr).toContain('/login loads 15')
  })

  it('reports pages still on the first design (TODO) without failing, unless --strict', () => {
    const dir = fakeBuild({ ...underBudget, '/': [200] })
    const relaxed = run(dir)
    expect(relaxed.status).toBe(0)
    expect(relaxed.stdout).toMatch(/\/\s+20\d\.\d KB\s+175 KB\s+over \(TODO\)/)
    const strict = run(dir, '--strict')
    expect(strict.status).toBe(1)
    expect(strict.stderr).toContain('/ loads 20')
    expect(strict.stderr).toContain('over its 175 KB budget')
  })

  it('fails when a budgeted page is missing from the build (with --strict)', () => {
    const rest: Record<string, number[]> = { ...underBudget }
    delete rest['/pipeline']
    const out = run(fakeBuild(rest), '--strict')
    expect(out.status).toBe(1)
    expect(out.stderr).toContain('/pipeline has a budget but is not in the build')
  })

  it('holds the new design (v2) pages to their budgets, never as TODO', () => {
    const over = run(fakeBuild({ ...underBudget, '/v2/settings': [200] }))
    expect(over.status).toBe(1)
    expect(over.stderr).toContain('/v2/settings loads 20')
    expect(over.stderr).toContain('over its 190 KB budget')
  })

  it('fails clearly without a build', () => {
    const dir = mkdtempSync(join(tmpdir(), 'bundles-'))
    dirs.push(dir)
    const out = run(dir)
    expect(out.status).toBe(1)
    expect(out.stderr).toContain('route-bundle-stats.json not found')
  })
})
