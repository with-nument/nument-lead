import { describe, expect, it } from 'vitest'
import { canonicalPath, isV2, uiCookie, v2PathFor, V2_ROUTES } from '@/lib/ui-flag'

describe('new design switch', () => {
  it('serves listed pages from /v2 and leaves the rest alone', () => {
    expect(V2_ROUTES).toContain('/')
    expect(v2PathFor('/')).toBe('/v2')
    expect(v2PathFor('/calls')).toBe('/v2/calls')
    expect(v2PathFor('/calls/')).toBe('/v2/calls')
    expect(v2PathFor('/leads')).toBeNull()
    expect(v2PathFor('/login')).toBeNull()
    expect(v2PathFor('/callsx')).toBeNull()
  })

  it('never rewrites a /v2 path again', () => {
    expect(v2PathFor('/v2')).toBeNull()
    expect(v2PathFor('/v2/calls', ['/v2/*', '/'])).toBeNull()
  })

  it('matches a whole section with /*', () => {
    const routes = ['/leads/*']
    expect(v2PathFor('/leads', routes)).toBe('/v2/leads')
    expect(v2PathFor('/leads/abc', routes)).toBe('/v2/leads/abc')
    expect(v2PathFor('/leadsx', routes)).toBeNull()
  })

  it('maps /v2 paths back to their normal URL', () => {
    expect(canonicalPath('/v2')).toBe('/')
    expect(canonicalPath('/v2/calls')).toBe('/calls')
    expect(canonicalPath('/calls')).toBe('/calls')
    expect(canonicalPath('/v2x')).toBe('/v2x')
  })

  it('only the exact cookie value turns it on', () => {
    expect(isV2('2')).toBe(true)
    expect(isV2('1')).toBe(false)
    expect(isV2(undefined)).toBe(false)
  })

  it('writes a year-long cookie on, and an expired one off', () => {
    expect(uiCookie(true, true)).toBe('nl_ui=2; Path=/; Max-Age=31536000; SameSite=Lax; Secure')
    expect(uiCookie(false, false)).toBe('nl_ui=; Path=/; Max-Age=0; SameSite=Lax')
  })
})
