import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  BulkStageInput,
  canMarkReplied,
  DEAL_CURRENCIES,
  DealInput,
  dealPatch,
  formatMoney,
  LOST_REASON_REQUIRED,
  LOST_REASON_VALUES,
  lostReasonLabel,
  needsLostReason,
  stageChange,
  StageInput,
} from '@/lib/outcomes'
import type { StepInput } from '@/lib/next-step'

const MIGRATION = readFileSync(fileURLToPath(new URL('../../../supabase/migrations/0016_outcomes.sql', import.meta.url)), 'utf8')
const checkList = (column: string) => {
  const m = MIGRATION.match(new RegExp(`check \\(${column} in\\s*\\(([^)]*)\\)`))
  return (m?.[1] ?? '').split(',').map((s) => s.trim().replace(/'/g, ''))
}

const ID = '00000000-0000-4000-8000-000000000001'
// 13 Nov 2026, 10:00 in India.
const NOW = new Date('2026-11-13T04:30:00Z')
const base: StepInput = { stage: 'contacted', wa_at: '2026-11-10', call_at: null, d3_at: null, d7_at: null, meeting_at: null }

describe('lost reasons and currencies match the database', () => {
  it('uses the check lists of migration 0016', () => {
    expect(LOST_REASON_VALUES).toEqual(checkList('lost_reason'))
    expect([...DEAL_CURRENCIES]).toEqual(checkList('deal_currency'))
  })

  it('labels every reason in plain words', () => {
    expect(lostReasonLabel('chose_other_vendor')).toBe('Chose another vendor')
    expect(lostReasonLabel('no_need_now')).toBe('No need right now')
    expect(lostReasonLabel('made_up')).toBeNull()
  })
})

describe('stageChange', () => {
  it('needs a reason for Lost and Not now only', () => {
    expect(needsLostReason('lost') && needsLostReason('not_now')).toBe(true)
    expect(['not_a_fit', 'wrong_contact', 'won', 'talking'].some(needsLostReason)).toBe(false)
    expect(stageChange(base, 'lost', { now: NOW })).toEqual({ ok: false, message: LOST_REASON_REQUIRED })
    expect(stageChange(base, 'not_now', { lostReason: null, now: NOW }).ok).toBe(false)
  })

  it('keeps the reason on Lost and clears it on every other stage', () => {
    expect(stageChange(base, 'lost', { lostReason: 'price', now: NOW })).toEqual({
      ok: true,
      patch: { stage: 'lost', lost_reason: 'price', next_step: null, due_at: null },
    })
    const reopened = stageChange({ ...base, stage: 'lost' }, 'talking', { lostReason: 'price', now: NOW })
    expect(reopened.ok && reopened.patch.lost_reason).toBeNull()
    const later = stageChange(base, 'not_now', { lostReason: 'no_need_now', now: NOW })
    expect(later.ok && later.patch).toMatchObject({ lost_reason: 'no_need_now', next_step: 'Check back', due_at: '2026-12-10' })
  })

  it('sets the meeting time when a discovery call is booked without one', () => {
    const booked = stageChange({ ...base, stage: 'talking' }, 'discovery_booked', { now: NOW })
    expect(booked.ok && booked.patch).toEqual({
      stage: 'discovery_booked',
      lost_reason: null,
      meeting_at: NOW.toISOString(),
      next_step: 'Discovery call',
      due_at: '2026-11-13',
    })
    const known = stageChange({ ...base, meeting_at: '2026-11-20T06:00:00Z' }, 'discovery_booked', { now: NOW })
    expect(known.ok && known.patch.meeting_at).toBeUndefined()
    expect(known.ok && known.patch.due_at).toBe('2026-11-20')
  })

  it('fills the first-message date for Contacted, as the sheet does', () => {
    const sent = stageChange({ ...base, stage: 'new', wa_at: null }, 'contacted', { now: NOW })
    expect(sent.ok && sent.patch).toMatchObject({ wa_at: '2026-11-13', next_step: 'Call', due_at: '2026-11-14' })
    const replied = stageChange(base, 'talking', { now: NOW })
    expect(replied.ok && replied.patch).toEqual({ stage: 'talking', lost_reason: null, next_step: 'Book discovery call', due_at: '2026-11-11' })
  })

  it('only offers Replied on a contacted lead', () => {
    expect(canMarkReplied('contacted')).toBe(true)
    expect(['new', 'talking', 'lost', null].some(canMarkReplied)).toBe(false)
  })
})

describe('stage inputs', () => {
  it('refuse Lost or Not now without a reason, with a plain message', () => {
    const one = StageInput.safeParse({ leadId: ID, stage: 'lost' })
    expect(one.success).toBe(false)
    expect(one.error?.issues[0]).toMatchObject({ message: LOST_REASON_REQUIRED, path: ['lostReason'] })
    expect(StageInput.safeParse({ leadId: ID, stage: 'lost', lostReason: 'price' }).success).toBe(true)
    expect(StageInput.safeParse({ leadId: ID, stage: 'won' }).success).toBe(true)
    expect(StageInput.safeParse({ leadId: ID, stage: 'lost', lostReason: 'too_busy' }).success).toBe(false)
    const bulk = BulkStageInput.safeParse({ ids: [ID], stage: 'not_now', lostReason: '' })
    expect(bulk.success).toBe(false)
    expect(BulkStageInput.safeParse({ ids: [], stage: 'talking' }).error?.issues[0]?.message).toBe('Select at least one lead.')
  })
})

describe('deal input', () => {
  it('writes only the fields the form sent', () => {
    expect(dealPatch(DealInput.parse({ leadId: ID, value: '150000' }))).toEqual({ deal_value_inr: 150000 })
    expect(dealPatch(DealInput.parse({ leadId: ID, value: '', retainer: '1500.555', currency: 'USD' }))).toEqual({
      deal_value_inr: null,
      retainer_monthly_value: 1500.56,
      deal_currency: 'USD',
    })
    expect(dealPatch(DealInput.parse({ leadId: ID, value: '90000', retainer: '' }))).toEqual({ deal_value_inr: 90000, retainer_monthly_value: null })
  })

  it('refuses unknown currencies and negative amounts', () => {
    expect(DealInput.safeParse({ leadId: ID, value: '1', currency: 'EUR' }).error?.issues[0]?.message).toBe('Choose a currency.')
    expect(DealInput.safeParse({ leadId: ID, value: '1', retainer: '-5' }).success).toBe(false)
  })

  it('formats money in its own currency, rupees with lakh grouping', () => {
    expect(formatMoney(150000)).toBe('₹1,50,000')
    expect(formatMoney(150000, 'USD')).toBe('$150,000')
    expect(formatMoney(5000, 'AED')).toMatch(/^AED\s5,000$/)
    expect(formatMoney(null, 'USD')).toBe('')
  })
})
