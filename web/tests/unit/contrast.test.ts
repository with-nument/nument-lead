import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { THEME_COLOR } from '@/styles/theme-color'

// WCAG contrast of the new design (v2), computed from the token values in src/styles/theme.css.
// The design is light only and monochrome. Text tokens (label-1..3, accent, status, who-answers) need 4.5:1
// on every surface and control fill. Stage dots and status dots sit beside words that carry the meaning,
// so they are decorative; they only have to stay in the calm palette (no blue or indigo anywhere).

type RGBA = { r: number; g: number; b: number; a: number }

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

const tokens = rootBlock(css)

function raw(name: string): string {
  const v = tokens.get(name)
  if (v === undefined) throw new Error(`${name} is not defined`)
  return v
}

function parseColor(value: string): RGBA {
  const v = value.trim()
  const ref = /^var\((--[\w-]+)\)$/.exec(v)
  if (ref) return parseColor(raw(ref[1]!))
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

const color = (name: string) => parseColor(raw(name))

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

/** Every opaque colour v2 text can end up on, named for the failure message. */
function backdrops(): Backdrop[] {
  const out: Backdrop[] = []
  const surfaces = ['--ui-wash-1', '--ui-panel', '--ui-bar', '--ui-tabbar', '--ui-overlay', '--ui-window', '--ui-field', '--ui-row-done', '--ui-thumb']
  for (const s of surfaces) {
    const base = color(s)
    out.push([s, base])
    for (const f of ['--ui-fill-1', '--ui-fill-2', '--ui-fill-3']) out.push([`${f} on ${s}`, over(color(f), base)])
  }
  // Initials circles and company tiles carry text but never sit under a control fill.
  out.push(['--ui-avatar', color('--ui-avatar')])
  return out
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

function failures(tokenNames: string[], min: number) {
  const out: string[] = []
  for (const t of tokenNames) {
    for (const [name, bg] of backdrops()) {
      const ratio = contrast(color(t), bg)
      if (ratio < min) out.push(`${t} on ${name}: ${ratio.toFixed(2)}`)
    }
  }
  return out
}

/** Hue (0-360) and saturation (0-1, HSL) of an opaque colour. */
function hueSat({ r, g, b }: RGBA) {
  const [R, G, B] = [r / 255, g / 255, b / 255]
  const max = Math.max(R, G, B)
  const min = Math.min(R, G, B)
  const l = (max + min) / 2
  const d = max - min
  if (d === 0) return { hue: 0, sat: 0 }
  const sat = d / (1 - Math.abs(2 * l - 1))
  let hue = max === R ? ((G - B) / d) % 6 : max === G ? (B - R) / d + 2 : (R - G) / d + 4
  hue *= 60
  if (hue < 0) hue += 360
  return { hue, sat }
}

describe('v2 contrast (light only)', () => {
  it('reads every token it needs', () => {
    expect(backdrops().length).toBeGreaterThan(30)
    for (const t of [...TEXT, '--ui-label-4']) expect(() => color(t)).not.toThrow()
  })

  it('label-1..3, accent, status and who-answers text reach 4.5:1 on every surface and control fill', () => {
    expect(failures(TEXT, 4.5)).toEqual([])
  })

  it('the selected segment (thumb) carries label-1 at 4.5:1', () => {
    expect(contrast(color('--ui-label-1'), color('--ui-thumb'))).toBeGreaterThanOrEqual(4.5)
  })

  it('text on the solid button reaches 4.5:1', () => {
    for (const fill of ['--ui-accent-fill', '--ui-accent-fill-hover']) {
      expect(contrast(color('--ui-on-accent'), color(fill)), fill).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('every grade letter reaches 4.5:1 wherever the mark sits', () => {
    const bad: string[] = []
    for (const g of ['a', 'b', 'c', 'd']) {
      for (const [name, bg] of backdrops()) {
        const mark = over(color(`--ui-grade-${g}`), bg)
        const ratio = contrast(color(`--ui-grade-${g}-ink`), mark)
        if (ratio < 4.5) bad.push(`grade ${g} on ${name}: ${ratio.toFixed(2)}`)
      }
    }
    expect(bad).toEqual([])
  })

  it('grades are outlined letters: a clear mark with a ring, A the darkest', () => {
    for (const g of ['a', 'b', 'c', 'd']) {
      expect(color(`--ui-grade-${g}`).a, g).toBe(0)
      expect(() => color(`--ui-grade-${g}-ring`), g).not.toThrow()
    }
    const page = color('--ui-wash-1')
    expect(contrast(over(color('--ui-grade-a-ring'), page), page)).toBeGreaterThan(contrast(over(color('--ui-grade-b-ring'), page), page))
  })

  it('label-4 is quieter than label-3 (placeholders only)', () => {
    const bg = color('--ui-wash-1')
    expect(contrast(color('--ui-label-4'), bg)).toBeLessThan(contrast(color('--ui-label-3'), bg))
  })

  it('the browser chrome colour matches the page', () => {
    expect(THEME_COLOR.toLowerCase()).toBe(raw('--ui-wash-1').toLowerCase())
  })
})

describe('v2 palette', () => {
  const colours = [...tokens.entries()].filter(([, v]) => /^(#|rgb|transparent)/.test(v))

  it('has no blue, indigo or violet: every colour is grey or a muted warm or green status hue', () => {
    expect(colours.length).toBeGreaterThan(40)
    const bad = colours.flatMap(([name, v]) => {
      const c = parseColor(v)
      const { hue, sat } = hueSat(c)
      return sat > 0.06 && hue >= 180 && hue <= 300 ? [`${name}: ${v}`] : []
    })
    expect(bad).toEqual([])
  })

  it('is calm: no saturated colour anywhere (status hues stay muted)', () => {
    const loud = colours.flatMap(([name, v]) => (hueSat(parseColor(v)).sat > 0.4 ? [`${name}: ${v}`] : []))
    expect(loud).toEqual([])
  })

  it('is light only and solid: no dark scheme, no blur, no gradients', () => {
    expect(css).not.toMatch(/prefers-color-scheme:\s*dark/)
    expect(css).not.toMatch(/backdrop-filter/)
    expect(css).not.toMatch(/gradient\(/)
  })

  it('has one solid button colour: the ink', () => {
    expect(raw('--ui-accent-fill').toLowerCase()).toBe('#111111')
  })
})
