import { describe, expect, it } from 'vitest'
import { BOARD_STAGES, CLOSED_STAGES, OPEN_STAGES, STAGES, stageOf } from '@/lib/stages'

// The stage check list from Step 2 (leads.stage).
const DB_STAGES = ['new', 'contacted', 'talking', 'discovery_booked', 'discovery_done', 'proposal_sent', 'won', 'retainer', 'lost', 'not_now', 'not_a_fit', 'wrong_contact']

describe('stages', () => {
  it('covers every database stage with a label and colours', () => {
    expect(STAGES.map((s) => s.value)).toEqual(DB_STAGES)
    for (const s of STAGES) {
      expect(s.label.length).toBeGreaterThan(0)
      expect(s.bg).toMatch(/^#[0-9A-F]{6}$/i)
      expect(s.fg).toMatch(/^#[0-9A-F]{6}$/i)
    }
  })

  it('falls back to New for unknown values', () => {
    expect(stageOf('something_else').value).toBe('new')
    expect(stageOf(null).label).toBe('New')
  })

  it('splits open and closed stages as in A.12.2', () => {
    expect(OPEN_STAGES).toEqual(['new', 'contacted', 'talking', 'discovery_booked', 'discovery_done', 'proposal_sent'])
    expect(CLOSED_STAGES).toEqual(['won', 'retainer', 'lost', 'not_now', 'not_a_fit', 'wrong_contact'])
    expect(BOARD_STAGES.map((s) => s.value as string)).not.toContain('new')
  })
})
