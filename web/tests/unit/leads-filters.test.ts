import { describe, expect, it } from 'vitest'
import { activeFilterCount, applyLeadFilters, EMPTY_FILTERS, filtersToQuery, parseLeadFilters, sanitizeSearch } from '@/lib/leads-filters'

describe('parseLeadFilters', () => {
  it('keeps only known values', () => {
    const f = parseLeadFilters(
      new URLSearchParams('stage=talking&stage=hacked&grade=A&grade=Z&signal=funding&pitch=fit_only&seg=clinics-in&seg=DROP%20TABLE&country=in&mobile=1&page=3&sort=score&dir=asc&owner=evil'),
    )
    expect(f.stage).toEqual(['talking'])
    expect(f.grade).toEqual(['A'])
    expect(f.signal).toEqual(['funding'])
    expect(f.pitch).toEqual(['fit_only'])
    expect(f.seg).toEqual(['clinics-in'])
    expect(f.country).toEqual(['in'])
    expect(f.mobile).toBe(true)
    expect(f.page).toBe(3)
    expect(f.sort).toBe('score')
    expect(f.dir).toBe('asc')
    expect(f.owner).toBe('')
  })

  it('round-trips through the URL and leaves defaults out', () => {
    const f = parseLeadFilters({ stage: ['contacted', 'talking'], q: ' dental ', grade: 'A' })
    expect(f.q).toBe('dental')
    const qs = filtersToQuery(f)
    expect(qs).toBe('q=dental&grade=A&stage=contacted&stage=talking')
    expect(parseLeadFilters(new URLSearchParams(qs))).toEqual(f)
    expect(filtersToQuery(EMPTY_FILTERS)).toBe('')
    expect(activeFilterCount(f)).toBe(3)
  })
})

describe('sanitizeSearch', () => {
  it('removes characters that would break a PostgREST or-filter', () => {
    expect(sanitizeSearch('a,b) or (c "d"* %e')).toBe('a b or c d e')
  })
})

describe('applyLeadFilters', () => {
  it('turns filters into PostgREST calls', () => {
    const calls: unknown[][] = []
    const builder = new Proxy(
      {},
      {
        get: (_, method: string) =>
          (...args: unknown[]) => {
            calls.push([method, ...args])
            return builder
          },
      },
    )
    const f = parseLeadFilters({ stage: 'talking', signal: 'hiring_frontdesk', mobile: '1', q: 'smile 98110', overdue: '1', from: '2026-11-01', to: '2026-11-12', owner: 'me' })
    applyLeadFilters(builder, f, { userId: 'u1', today: '2026-11-12' })
    expect(calls).toContainEqual(['in', 'stage', ['talking']])
    expect(calls).toContainEqual(['in', 'top_signal_type', ['hiring_frontdesk']])
    expect(calls).toContainEqual(['eq', 'phone_type', 'mobile'])
    expect(calls).toContainEqual(['eq', 'owner_id', 'u1'])
    expect(calls).toContainEqual(['lt', 'due_at', '2026-11-12'])
    expect(calls).toContainEqual(['gte', 'created_at', '2026-10-31T18:30:00.000Z'])
    expect(calls).toContainEqual(['lt', 'created_at', '2026-11-12T18:30:00.000Z'])
    expect(calls).toContainEqual(['or', 'name.ilike.*smile 98110*,web_domain.ilike.*smile 98110*,phone_e164.ilike.*98110*'])
  })
})
