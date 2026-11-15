import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

// The new design (v2) only speaks in tokens from src/styles/theme.css. No hex colours, no colour
// functions, no Tailwind palette classes, no v1 kit names, and no v1 components or helpers.
// The sign-in pages are v2 as well.

const SRC = path.join(__dirname, '../../src')
const V2_DIRS = ['app/(v2)', 'components/ui2', 'components/shell2'] // sign-in is classic again until the kit-based redesign (16 Nov 2026)

function files(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name)
    if (statSync(p).isDirectory()) out.push(...files(p))
    else if (/\.(tsx?|css)$/.test(name)) out.push(p)
  }
  return out
}

const PALETTE = 'slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose'
const COLOR_UTIL = 'bg|text|border(?:-[trblxyse])?|ring(?:-offset)?|outline|fill|stroke|from|via|to|divide|placeholder|caret|accent|decoration|shadow|inset-shadow|inset-ring'
const V1_NAMES = 'tx-[1-4]|canvas|surface(?:-[23])?|line(?:-2)?|slate|ok|ok-bg|warn|warn-bg|warn-ink|bad|bad-bg'

const RULES: { name: string; re: RegExp }[] = [
  { name: 'hex colour', re: /(?<![&\w])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![\w-])/gi },
  { name: 'colour function', re: /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/g },
  { name: 'palette class', re: new RegExp(`(?<![\\w-])(?:${COLOR_UTIL})-(?:${PALETTE})-\\d{2,3}(?![\\w-])`, 'g') },
  { name: 'black or white class', re: new RegExp(`(?<![\\w-])(?:${COLOR_UTIL})-(?:black|white)(?![\\w-])`, 'g') },
  { name: 'v1 colour name', re: new RegExp(`(?<![\\w-])(?:${COLOR_UTIL})-(?:${V1_NAMES})(?![\\w-])`, 'g') },
  // Only as a class (after a quote, space or variant colon), so an import path like './skeleton' is fine.
  { name: 'v1 utility', re: /(?<=["'`\s:])(?:label-mono|btn-ink|wordmark|shadow-menu|shadow-dialog|focus-ring|font-display|font-sans|font-mono|skeleton|tabular|animate-(?:drawer|fade|pop)-in)(?=["'`\s])/g },
  { name: 'v1 component or helper', re: /from ['"]@\/(?:components\/(?:ui|shell|skeletons)\b|lib\/cn['"])/g },
  { name: 'sonner (use the ui2 toast)', re: /from ['"]sonner['"]/g },
  // label-4 is too light for reading: placeholders (and disabled controls) only.
  { name: 'label-4 outside a placeholder', re: /(?<!(?:placeholder|disabled|aria-disabled):)(?<![\w-])(?:text|fill|stroke)-label-4(?![\w-])/g },
]

function violations(file: string): string[] {
  const text = readFileSync(file, 'utf8')
  const out: string[] = []
  for (const { name, re } of RULES) {
    for (const m of text.matchAll(re)) {
      const line = text.slice(0, m.index).split('\n').length
      out.push(`${path.relative(SRC, file)}:${line} ${name}: ${m[0]}`)
    }
  }
  return out
}

describe('v2 design lint', () => {
  const all = V2_DIRS.flatMap((d) => files(path.join(SRC, d)))

  it('finds the v2 code', () => {
    expect(all.length).toBeGreaterThan(10)
    for (const d of V2_DIRS) expect(all.some((f) => f.startsWith(path.join(SRC, d))), d).toBe(true)
  })

  it('uses tokens only: no hex, colour functions, palette classes, v1 names or v1 components', () => {
    expect(all.flatMap(violations)).toEqual([])
  })

  it('catches what it should', () => {
    const probe = (snippet: string) => RULES.filter(({ re }) => new RegExp(re.source, re.flags).test(snippet)).map((r) => r.name)
    expect(probe('className="bg-blue-500"')).toEqual(['palette class'])
    expect(probe("color: '#1f1f1f'")).toEqual(['hex colour'])
    expect(probe('bg-[rgb(0_0_0/0.2)]')).toEqual(['colour function'])
    expect(probe('text-white')).toEqual(['black or white class'])
    expect(probe('text-tx-3 border-line-2')).toEqual(['v1 colour name'])
    expect(probe("import { cn } from '@/lib/cn'")).toEqual(['v1 component or helper'])
    expect(probe('text-label-4')).toEqual(['label-4 outside a placeholder'])
    expect(probe('className="skeleton h-4"')).toEqual(['v1 utility'])
    // Tokens and look-alikes that are fine.
    expect(probe('placeholder:text-label-4 text-line-owner bg-fill-1 text-status-bad skeleton-2 href="#main" &#8217;')).toEqual([])
    expect(probe("import { Skeleton } from './skeleton'")).toEqual([])
  })
})
