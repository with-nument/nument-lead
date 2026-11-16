import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'
import { REVEAL_NOW } from '@/components/ui2/scope'

// The v2 first-paint script turns off React's 300 ms reveal batching for streamed sections (scope.tsx). It
// relies on one line of React's streaming runtime: when $RT is not a number, a finished section is revealed
// on the next animation frame. If an upgrade changes that line, this test fails so the trick is looked at
// again (the page still works either way: it only falls back to the default batching).
const require = createRequire(import.meta.url)

describe('reveal streamed sections at once', () => {
  it('React reveals on the next frame while $RT is not a number', () => {
    const file = require.resolve('next/dist/compiled/react-dom/cjs/react-dom-server.node.production.js')
    const runtime = readFileSync(file, 'utf8')
    expect(runtime).toContain('"number"!==typeof $RT?requestAnimationFrame($RV.bind(null,$RB))')
    expect(runtime).toContain('requestAnimationFrame(function(){$RT=performance.now()});')
  })

  it('keeps $RT from ever becoming a number', () => {
    const typeAfter = runInNewContext(`window = this; ${REVEAL_NOW}; $RT = 123; $RT = performance.now(); typeof $RT`, { performance })
    expect(typeAfter).toBe('undefined')
  })
})
