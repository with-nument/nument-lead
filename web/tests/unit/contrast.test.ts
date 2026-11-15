import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { THEME_COLOR } from '@/styles/theme-color'

// WCAG contrast of the new design (v2), computed from the token values in src/styles/theme.css.
// Text tokens (label-1..3, accent, status, who-answers) need 4.5:1 over every material, translucent
// and solid, at every stop of the wash, in light and dark. Stage dots are graphics: 3:1.

type RGBA = { r: number; g: number; b: number; a: number }
type Scheme = 'light' | 'dark'

const css = readFileSync(path.join(__dirname, '../../src/styles/theme.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

/** The declarations of the first `:root { }` block found in `source`. */
function rootBlock(source: string): Map<string, string> {
  const start = source.search(/:root\s*\{/)
  if (start < 0) throw new Error('no :root block')
  const open = source.indexOf('{', start)
  const close = source.indexOf('}', open)
  const out = new Map<string, string>()
  for (const m of source.slice(open + 1, close).matchAll(/(--ui-[\w-]+)\s*:\s*([^;]+);/g)) out.set(m[1]!, m[2]!.trim())
  return out
}

const light = rootBlock(css)
const darkAt = css.search(/@media\s*\(prefers-color-scheme:\s*dark\)\s*\{/)
const dark = rootBlock(css.slice(darkAt))

function raw(scheme: Scheme, name: string): string {
  const v = (scheme === 'dark' ? dark.get(name) : undefined) ?? light.get(name)
  if (v === undefined) throw new Error(`${name} is not defined`)
  return v
}

function parseColor(value: string, scheme: Scheme): RGBA {
  const v = value.trim()
  const ref = /^var\((--[\w-]+)\)$/.exec(v)
  if (ref) return parseColor(raw(scheme, ref[1]!), scheme)
  if (v === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
  const hex = /^#([0-9a-f]{3,8})$/i.exec(v)
  if (hex) {
    let h = hex[1]!
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join('')
    const n = (i: number) => parseInt(h.slice(i, i + 2), 16)
    return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 }
  }
  const fn = /^rgba?\(([^)]+)\)$/i.exec(v)
  if (fn) {
    const parts = fn[1]!
      .replace('/', ' ')
      .split(/[\s,]+/)
      .filter(Boolean)
    const num = (s: string, max: number) => (s.endsWith('%') ? (parseFloat(s) / 100) * max : parseFloat(s))
    return { r: num(parts[0]!, 255), g: num(parts[1]!, 255), b: num(parts[2]!, 255), a: parts[3] === undefined ? 1 : num(parts[3], 1) }
  }
  throw new Error(`cannot read colour "${value}"`)
}

const color = (scheme: Scheme, name: string) => parseColor(raw(scheme, name), scheme)

/** `top` painted over an opaque `bottom` (browsers composite in gamma-encoded sRGB). */
function over(top: RGBA, bottom: RGBA): RGBA {
  const mix = (t: number, b: number) => t * top.a + b * (1 - top.a)
  return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a: 1 }
}

function luminance({ r, g, b }: RGBA) {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function contrast(fg: RGBA, bg: RGBA) {
  const text = fg.a < 1 ? over(fg, bg) : fg
  const [a, b] = [luminance(text), luminance(bg)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

type Backdrop = [name: string, color: RGBA]

/**
 * Every opaque colour v2 text can end up on, named for the failure message. `materials` are the wash,
 * panels, bars, overlays and the sign-in window (translucent over every wash stop, and solid), plus
 * the control fills inside them. `onWash` are control fills sitting straight on the wash.
 */
function backdrops(scheme: Scheme): { materials: Backdrop[]; onWash: Backdrop[] } {
  const c = (n: string) => color(scheme, n)
  const washes: Backdrop[] = []
  for (const w of ['--ui-wash-1', '--ui-wash-2', '--ui-wash-3']) {
    washes.push([w, c(w)])
    for (const glow of ['--ui-wash-glow-1', '--ui-wash-glow-2']) washes.push([`${glow} over ${w}`, over(c(glow), c(w))])
  }
  const materials: Backdrop[] = []
  const onWash: Backdrop[] = []
  for (const [wn, w] of washes) {
    const panel = over(c('--ui-panel'), w)
    const bar = over(c('--ui-bar'), w)
    const overlay = over(c('--ui-overlay'), w)
    const win = over(c('--ui-window'), w)
    materials.push(
      [`wash (${wn})`, w],
      [`panel on ${wn}`, panel],
      [`bar on ${wn}`, bar],
      [`bar over a panel on ${wn}`, over(c('--ui-bar'), panel)],
      [`overlay on ${wn}`, overlay],
      [`overlay over a panel on ${wn}`, over(c('--ui-overlay'), panel)],
      [`window on ${wn}`, win],
      [`field in the window on ${wn}`, over(c('--ui-field'), win)],
      [`field in an overlay on ${wn}`, over(c('--ui-field'), overlay)],
      [`fill-1 on a panel on ${wn}`, over(c('--ui-fill-1'), panel)],
      [`fill-2 on a panel on ${wn}`, over(c('--ui-fill-2'), panel)],
      [`fill-1 on the bar on ${wn}`, over(c('--ui-fill-1'), bar)],
      [`fill-1 in an overlay on ${wn}`, over(c('--ui-fill-1'), overlay)],
    )
    onWash.push([`fill-1 on ${wn}`, over(c('--ui-fill-1'), w)], [`fill-2 on ${wn}`, over(c('--ui-fill-2'), w)])
  }
  for (const solid of ['--ui-panel-solid', '--ui-bar-solid', '--ui-overlay-solid', '--ui-window-solid']) {
    materials.push([solid, c(solid)], [`fill-1 on ${solid}`, over(c('--ui-fill-1'), c(solid))])
  }
  materials.push(['field on the solid window', over(c('--ui-field'), c('--ui-window-solid'))])
  return { materials, onWash }
}

const TEXT = [
  '--ui-label-1',
  '--ui-label-2',
  '--ui-label-3',
  '--ui-accent',
  '--ui-ok',
  '--ui-warn',
  '--ui-bad',
  '--ui-line-owner',
  '--ui-line-front-desk',
  '--ui-line-bot',
  '--ui-line-other',
]
const STAGES = ['new', 'contacted', 'replied', 'call-booked', 'call-done', 'proposal', 'won', 'retainer', 'lost', 'not-now', 'not-a-fit', 'wrong-contact']

function failures(scheme: Scheme, tokens: string[], min: number, where: 'materials' | 'onWash' = 'materials') {
  const out: string[] = []
  for (const t of tokens) {
    for (const [name, bg] of backdrops(scheme)[where]) {
      const ratio = contrast(color(scheme, t), bg)
      if (ratio < min) out.push(`${t} on ${name}: ${ratio.toFixed(2)}`)
    }
  }
  return out
}

describe.each<Scheme>(['light', 'dark'])('v2 contrast, %s', (scheme) => {
  it('reads every token it needs', () => {
    expect(backdrops(scheme).materials.length).toBeGreaterThan(100)
    for (const t of [...TEXT, '--ui-label-4']) expect(() => color(scheme, t)).not.toThrow()
  })

  it('label-1..3, accent, status and who-answers text reach 4.5:1 on every material', () => {
    expect(failures(scheme, TEXT, 4.5)).toEqual([])
  })

  it('buttons and segments sitting straight on the wash keep their text (label-1, label-2, destructive) at 4.5:1', () => {
    expect(failures(scheme, ['--ui-label-1', '--ui-label-2', '--ui-bad'], 4.5, 'onWash')).toEqual([])
  })

  it('the selected segment (thumb) carries label-1 at 4.5:1', () => {
    expect(contrast(color(scheme, '--ui-label-1'), color(scheme, '--ui-thumb'))).toBeGreaterThanOrEqual(4.5)
  })

  it('text on the accent fill reaches 4.5:1', () => {
    for (const fill of ['--ui-accent-fill', '--ui-accent-fill-hover']) {
      expect(contrast(color(scheme, '--ui-on-accent'), color(scheme, fill)), fill).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('every grade letter reaches 4.5:1 on its mark, wherever the mark sits', () => {
    const bad: string[] = []
    for (const g of ['a', 'b', 'c', 'd']) {
      for (const [name, bg] of backdrops(scheme).materials) {
        const mark = over(color(scheme, `--ui-grade-${g}`), bg)
        const ratio = contrast(color(scheme, `--ui-grade-${g}-ink`), mark)
        if (ratio < 4.5) bad.push(`grade ${g} on ${name}: ${ratio.toFixed(2)}`)
      }
    }
    expect(bad).toEqual([])
  })

  it('stage dots reach 3:1 (graphics) on every material', () => {
    expect(
      failures(
        scheme,
        STAGES.map((s) => `--ui-stage-${s}`),
        3,
      ),
    ).toEqual([])
  })

  it('label-4 is quieter than label-3 (placeholders only)', () => {
    const bg = color(scheme, '--ui-wash-3')
    expect(contrast(color(scheme, '--ui-label-4'), bg)).toBeLessThan(contrast(color(scheme, '--ui-label-3'), bg))
  })

  it('the browser chrome colour matches the top of the wash', () => {
    const entry = THEME_COLOR.find((t) => t.media.includes(scheme))
    expect(entry?.color.toLowerCase()).toBe(raw(scheme, '--ui-wash-1').toLowerCase())
  })
})

describe('v2 materials', () => {
  it('panels are about 82% white and never blurred', () => {
    expect(color('light', '--ui-panel').a).toBeCloseTo(0.82, 2)
    expect(raw('light', '--ui-panel-bg')).toBe('var(--ui-panel)')
    expect(css).not.toMatch(/@utility material-panel\s*\{[^}]*backdrop-filter/)
  })

  it('every material has a solid fallback for no blur, reduced transparency and tests', () => {
    for (const trigger of [/@supports not \(\(backdrop-filter/, /@media \(prefers-reduced-transparency: reduce\)/, /html\[data-materials='solid'\]/]) {
      const at = css.search(trigger)
      expect(at, String(trigger)).toBeGreaterThan(-1)
      const block = css.slice(at, css.indexOf('}', css.indexOf('{', at) + 1) + 1)
      for (const m of ['panel', 'bar', 'overlay', 'window']) expect(block).toContain(`--ui-${m}-bg: var(--ui-${m}-solid)`)
      for (const b of ['bar', 'overlay', 'window']) expect(block).toContain(`--ui-blur-${b}: none`)
    }
  })
})
