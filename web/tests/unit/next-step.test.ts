import { describe, expect, it } from 'vitest'
import { nextStepAndDue, type StepInput } from '@/lib/next-step'

const TODAY = '2026-11-12'
const base: StepInput = { stage: 'new', wa_at: null, call_at: null, d3_at: null, d7_at: null, meeting_at: null }

// Cases mirror next_step_and_due() in plan 13.5.4, so the app, the sheet and the engine agree.
describe('nextStepAndDue', () => {
  it('leaves new, unsent leads to the engine', () => {
    expect(nextStepAndDue(base, TODAY)).toBeUndefined()
  })

  it('walks the contact sequence', () => {
    expect(nextStepAndDue({ ...base, stage: 'contacted' }, TODAY)).toEqual({ next_step: 'Call', due_at: TODAY })
    const sent = { ...base, stage: 'contacted', wa_at: '2026-11-10' }
    expect(nextStepAndDue(sent, TODAY)).toEqual({ next_step: 'Call', due_at: '2026-11-11' })
    expect(nextStepAndDue({ ...sent, call_at: '2026-11-11' }, TODAY)).toEqual({ next_step: 'Day 3 follow-up', due_at: '2026-11-13' })
    expect(nextStepAndDue({ ...sent, call_at: '2026-11-11', d3_at: '2026-11-13' }, TODAY)).toEqual({ next_step: 'Last touch', due_at: '2026-11-17' })
    expect(nextStepAndDue({ ...sent, call_at: '2026-11-11', d3_at: '2026-11-13', d7_at: '2026-11-17' }, TODAY)).toEqual({
      next_step: 'Move to Not now',
      due_at: '2026-11-18',
    })
  })

  it('handles the later stages', () => {
    expect(nextStepAndDue({ ...base, stage: 'talking', wa_at: '2026-11-10' }, TODAY)).toEqual({ next_step: 'Book discovery call', due_at: '2026-11-11' })
    expect(nextStepAndDue({ ...base, stage: 'discovery_booked', meeting_at: '2026-11-14T05:00:00Z' }, TODAY)).toEqual({ next_step: 'Discovery call', due_at: '2026-11-14' })
    expect(nextStepAndDue({ ...base, stage: 'discovery_done', meeting_at: '2026-11-14T05:00:00Z' }, TODAY)).toEqual({ next_step: 'Send proposal', due_at: '2026-11-16' })
    expect(nextStepAndDue({ ...base, stage: 'proposal_sent' }, TODAY)).toEqual({ next_step: 'Follow up proposal', due_at: TODAY })
    expect(nextStepAndDue({ ...base, stage: 'not_now', wa_at: '2026-11-01' }, TODAY)).toEqual({ next_step: 'Check back', due_at: '2026-12-01' })
  })

  it('closes the loop on closed stages', () => {
    expect(nextStepAndDue({ ...base, stage: 'won' }, TODAY)).toEqual({ next_step: 'Kick-off', due_at: null })
    expect(nextStepAndDue({ ...base, stage: 'retainer' }, TODAY)).toEqual({ next_step: 'Monthly review', due_at: null })
    expect(nextStepAndDue({ ...base, stage: 'wrong_contact' }, TODAY)).toEqual({ next_step: 'Find the right number', due_at: null })
    expect(nextStepAndDue({ ...base, stage: 'lost' }, TODAY)).toEqual({ next_step: null, due_at: null })
  })

  it('uses the India date of a meeting', () => {
    // 20:00 UTC on the 13th is the 14th in India.
    expect(nextStepAndDue({ ...base, stage: 'discovery_booked', meeting_at: '2026-11-13T20:00:00Z' }, TODAY)?.due_at).toBe('2026-11-14')
  })
})
