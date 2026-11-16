import { describe, expect, it } from 'vitest'
import { canonicalPath, isV2, uiCookie, v2PathFor, V2_ROUTES } from '@/lib/ui-flag'

describe('new design switch', () => {
  it('serves listed pages from /v2 and leaves the rest alone', () => {
    expect(V2_ROUTES).toContain('/')
    expect(v2PathFor('/')).toBe('/v2')
    expect(v2PathFor('/calls')).toBe('/v2/calls')
    expect(v2PathFor('/calls/')).toBe('/v2/calls')
    expect(v2PathFor('/settings')).toBeNull()
    expect(v2PathFor('/login')).toBeNull()
    expect(v2PathFor('/callsx')).toBeNull()
  })

  it('never rewrites a /v2 path again', () => {
    expect(v2PathFor('/v2')).toBeNull()
    expect(v2PathFor('/v2/calls', ['/v2/*', '/'])).toBeNull()
  })

  it('serves Leads, a lead and Deals, but never the CSV export', () => {
    const id = '0f8fad5b-d9cb-469f-a165-70867728950e'
    expect(v2PathFor('/leads')).toBe('/v2/leads')
    expect(v2PathFor(`/leads/${id}`)).toBe(`/v2/leads/${id}`)
    expect(v2PathFor(`/leads/${id.toUpperCase()}/`)).toBe(`/v2/leads/${id.toUpperCase()}`)
    expect(v2PathFor('/leads/export')).toBeNull()
    expect(v2PathFor('/leads/not-a-uuid')).toBeNull()
    expect(v2PathFor(`/leads/${id}/more`)).toBeNull()
    expect(v2PathFor('/deals')).toBe('/v2/deals')
  })

  it('matches a :uuid segment only with a UUID', () => {
    const routes = ['/x/:uuid/y']
    expect(v2PathFor('/x/0f8fad5b-d9cb-469f-a165-70867728950e/y', routes)).toBe('/v2/x/0f8fad5b-d9cb-469f-a165-70867728950e/y')
    expect(v2PathFor('/x/abc/y', routes)).toBeNull()
    expect(v2PathFor('/x/0f8fad5b-d9cb-469f-a165-70867728950e', routes)).toBeNull()
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
