// Next step and due date: the TypeScript twin of the sheet formula and the engine (plan 13.5.4).
// All three must agree, so this file mirrors next_step_and_due() line by line and is unit-tested.
import { addDays, istDate } from '@/lib/dates'

export type StepInput = {
  stage: string
  wa_at: string | null
  call_at: string | null
  d3_at: string | null
  d7_at: string | null
  /** timestamptz; its India date is used. */
  meeting_at: string | null
}

export type StepResult = { next_step: string | null; due_at: string | null }

/**
 * Returns the next step for a lead, or `undefined` for a New lead that has not been messaged yet
 * (the engine sets that one from the daily send quota, so the app leaves it alone).
 */
export function nextStepAndDue(lead: StepInput, today: string): StepResult | undefined {
  const s = lead.stage
  const { wa_at: wa, call_at: call, d3_at: d3, d7_at: d7 } = lead
  const mt = lead.meeting_at ? istDate(lead.meeting_at) : null
  const touches = [wa, call, d3, d7].filter((d): d is string => Boolean(d)).sort()
  const last = touches.at(-1) ?? null
  const step = (next_step: string, due_at: string | null): StepResult => ({ next_step: next_step || null, due_at })

  if (s === 'won') return step('Kick-off', null)
  if (s === 'retainer') return step('Monthly review', null)
  if (s === 'wrong_contact') return step('Find the right number', null)
  if (s === 'lost' || s === 'not_a_fit') return step('', null)
  if (s === 'not_now') return step('Check back', addDays(last ?? today, 30))
  if (s === 'proposal_sent') return step('Follow up proposal', mt ? addDays(mt, 4) : today)
  if (s === 'discovery_done') return step('Send proposal', mt ? addDays(mt, 2) : today)
  if (s === 'discovery_booked') return step('Discovery call', mt ?? today)
  if (s === 'talking') return step('Book discovery call', last ? addDays(last, 1) : today)
  if (s === 'contacted' && !wa) return step('Call', today)
  if (!wa) return undefined
  if (!call) return step('Call', addDays(wa, 1))
  if (!d3) return step('Day 3 follow-up', addDays(wa, 3))
  if (!d7) return step('Last touch', addDays(wa, 7))
  return step('Move to Not now', addDays(d7, 1))
}
