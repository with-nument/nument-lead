// RFC 4180 CSV. Cells that a spreadsheet would run as a formula are prefixed with a quote mark.

const FORMULA = /^[=+\-@\t\r]/

function cell(v: unknown): string {
  if (v === null || v === undefined) return ''
  let s = typeof v === 'object' ? JSON.stringify(v) : String(v)
  // Plain numbers and phone numbers ("+919811012345", "-12.5") are safe as they are.
  if (FORMULA.test(s) && !/^[+-]?\d[\d .]*$/.test(s)) s = `'${s}`
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv(rows: Record<string, unknown>[], columns?: { key: string; label: string }[]): string {
  const cols = columns ?? Object.keys(rows[0] ?? {}).map((k) => ({ key: k, label: k }))
  const head = cols.map((c) => cell(c.label)).join(',')
  const body = rows.map((r) => cols.map((c) => cell(r[c.key])).join(','))
  // BOM so Excel opens UTF-8 (rupee sign, names) correctly.
  return `﻿${[head, ...body].join('\r\n')}\r\n`
}
