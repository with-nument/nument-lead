import { describe, expect, it } from 'vitest'
import { toCsv } from '@/lib/csv'

describe('toCsv', () => {
  it('escapes quotes, commas and new lines, with a BOM for Excel', () => {
    const csv = toCsv([{ a: 'He said "hi"', b: 'x,y', c: 'line1\nline2', d: null }], [
      { key: 'a', label: 'A' },
      { key: 'b', label: 'B' },
      { key: 'c', label: 'C' },
      { key: 'd', label: 'D' },
    ])
    expect(csv.startsWith('﻿')).toBe(true)
    expect(csv).toBe('﻿A,B,C,D\r\n"He said ""hi""","x,y","line1\nline2",\r\n')
  })

  it('neutralises spreadsheet formulas but keeps numbers and phones', () => {
    const csv = toCsv([{ f: '=HYPERLINK("x")', p: '+919811012345', n: '-12.5' }])
    expect(csv).toContain(`"'=HYPERLINK(""x"")"`)
    expect(csv).toContain(',+919811012345,')
    expect(csv).toContain(',-12.5\r\n')
  })
})
