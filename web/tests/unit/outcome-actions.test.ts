import { beforeEach, describe, expect, it, vi } from 'vitest'

// The server actions behind Replied, the stage menu, the board, bulk moves and the deal form, run against a
// small in-memory stand-in for Supabase. Auth, revalidation and the timeline helper are mocked; the rules
// themselves (lib/outcomes) are real.

type Row = Record<string, unknown>
type Write = { table: string; patch: Row; id: unknown }

const h = vi.hoisted(() => ({
  user: { id: '00000000-0000-4000-8000-0000000000aa', role: 'admin' as string },
  leads: {} as Record<string, Record<string, unknown>>,
  writes: [] as { table: string; patch: Record<string, unknown>; id: unknown }[],
  adminWrites: [] as { table: string; patch: Record<string, unknown>; id: unknown }[],
  activity: [] as unknown[][],
}))

/** Enough of the supabase-js query builder for these actions: select, update, eq, in, maybeSingle, await. */
function fakeClient(writes: Write[]) {
  return {
    from(table: string) {
      let patch: Row | undefined
      let ids: string[] | undefined
      const filters: Row = {}
      const settle = () => {
        if (patch) {
          writes.push({ table, patch, id: filters.id })
          const row = table === 'leads' && typeof filters.id === 'string' ? h.leads[filters.id] : undefined
          if (row) Object.assign(row, patch)
          return { data: null, error: null }
        }
        if (ids) return { data: ids.filter((id) => h.leads[id]).map((id) => ({ id, ...h.leads[id] })), error: null }
        return { data: null, error: null }
      }
      const q = {
        select: () => q,
        update: (p: Row) => ((patch = p), q),
        eq: (col: string, v: unknown) => ((filters[col] = v), q),
        in: (_col: string, v: string[]) => ((ids = v), q),
        maybeSingle: async () => ({ data: typeof filters.id === 'string' ? (h.leads[filters.id] ?? null) : null, error: null }),
        then: (ok: (v: unknown) => unknown, bad?: (e: unknown) => unknown) => Promise.resolve(settle()).then(ok, bad),
      }
      return q
    },
  }
}

vi.mock('server-only', () => ({}))
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }))
vi.mock('@/lib/revalidate', () => ({ revalidateLead: vi.fn() }))
vi.mock('@/lib/auth', () => ({ requireRole: vi.fn(async () => h.user) }))
vi.mock('@/lib/activity', () => ({ logActivity: vi.fn(async (...args: unknown[]) => void h.activity.push(args.slice(1))) }))
vi.mock('@/lib/supabase/server', () => ({ createClient: vi.fn(async () => fakeClient(h.writes)) }))
vi.mock('@/lib/supabase/admin', () => ({ createAdminClient: vi.fn(() => fakeClient(h.adminWrites)) }))

const { markReplied } = await import('@/app/(app)/actions')
const { setDealValue, setLostReason, updateStage } = await import('@/app/(app)/leads/[id]/actions')
const { bulkUpdateStage } = await import('@/app/(app)/leads/actions')

const A = '00000000-0000-4000-8000-000000000001'
const B = '00000000-0000-4000-8000-000000000002'
const lead = (stage: string, extra: Row = {}): Row => ({
  stage,
  wa_at: '2026-11-10',
  call_at: null,
  d3_at: null,
  d7_at: null,
  meeting_at: null,
  skipped_until: null,
  next_step: 'Day 3 follow-up',
  due_at: '2026-11-13',
  phone_e164: '+919800000001',
  ...extra,
})

beforeEach(() => {
  h.leads = { [A]: lead('contacted'), [B]: lead('talking') }
  h.writes.length = 0
  h.adminWrites.length = 0
  h.activity.length = 0
})

describe('markReplied', () => {
  it('moves a contacted lead to Talking in one step and logs the reply', async () => {
    const r = await markReplied(A)
    expect(r).toMatchObject({ ok: true, message: 'Marked as replied', data: { stage: 'contacted', next_step: 'Day 3 follow-up' } })
    expect(h.writes).toEqual([{ table: 'leads', id: A, patch: { stage: 'talking', lost_reason: null, next_step: 'Book discovery call', due_at: '2026-11-11' } }])
    expect(h.activity).toEqual([[A, h.user.id, 'reply']])
  })

  it('never moves a lead back from a later stage', async () => {
    const r = await markReplied(B)
    expect(r.ok).toBe(false)
    expect(r.message).toContain('Talking')
    expect(h.writes).toEqual([])
  })
})

describe('updateStage', () => {
  it('asks for a reason before Lost or Not now and saves nothing without one', async () => {
    expect(await updateStage({ leadId: B, stage: 'lost' })).toEqual({ ok: false, message: 'Choose why it closed.', fieldErrors: undefined })
    expect(h.writes).toEqual([])
  })

  it('saves the reason with the stage and puts it on the timeline', async () => {
    const r = await updateStage({ leadId: B, stage: 'not_now', lostReason: 'no_need_now' })
    expect(r.ok).toBe(true)
    expect(h.writes[0]?.patch).toMatchObject({ stage: 'not_now', lost_reason: 'no_need_now', next_step: 'Check back' })
    expect(h.activity).toEqual([[B, h.user.id, 'edit', { field: 'lost_reason', reason: 'no_need_now' }]])
  })

  it('sets the meeting time on Discovery booked only when there is none', async () => {
    const before = Date.now()
    await updateStage({ leadId: B, stage: 'discovery_booked' })
    const at = Date.parse(String(h.writes[0]?.patch.meeting_at))
    expect(at).toBeGreaterThanOrEqual(before)
    h.leads[A] = lead('talking', { meeting_at: '2026-11-20T06:00:00Z' })
    await updateStage({ leadId: A, stage: 'discovery_booked' })
    expect(h.writes[1]?.patch).not.toHaveProperty('meeting_at')
    expect(h.writes[1]?.patch).toMatchObject({ next_step: 'Discovery call', due_at: '2026-11-20' })
  })

  it('clears an old reason when a closed lead is reopened', async () => {
    h.leads[A] = lead('lost', { lost_reason: 'price' })
    await updateStage({ leadId: A, stage: 'talking' })
    expect(h.writes[0]?.patch).toMatchObject({ stage: 'talking', lost_reason: null })
  })
})

describe('setLostReason', () => {
  it('fills in the reason of a lead that is already closed', async () => {
    h.leads[A] = lead('lost')
    expect((await setLostReason({ leadId: A, reason: 'chose_other_vendor' })).ok).toBe(true)
    expect(h.writes).toEqual([{ table: 'leads', id: A, patch: { lost_reason: 'chose_other_vendor' } }])
  })

  it('refuses open leads and unknown reasons', async () => {
    expect((await setLostReason({ leadId: B, reason: 'price' })).ok).toBe(false)
    expect((await setLostReason({ leadId: A, reason: 'busy' as never })).message).toBe('Choose why it closed.')
    expect(h.writes).toEqual([])
  })
})

describe('bulkUpdateStage', () => {
  it('needs one reason for every lead moved to Lost', async () => {
    expect(await bulkUpdateStage({ ids: [A, B], stage: 'lost' })).toMatchObject({ ok: false, message: 'Choose why it closed.' })
    expect(h.writes).toEqual([])
    expect((await bulkUpdateStage({ ids: [A, B], stage: 'lost', lostReason: 'no_reply' })).ok).toBe(true)
    expect(h.writes.map((w) => [w.id, w.patch.lost_reason])).toEqual([
      [A, 'no_reply'],
      [B, 'no_reply'],
    ])
    expect(h.activity).toHaveLength(2)
  })

  it('sets the meeting time on Discovery booked like a single move', async () => {
    h.leads[B] = lead('talking', { meeting_at: '2026-11-20T06:00:00Z' })
    await bulkUpdateStage({ ids: [A, B], stage: 'discovery_booked' })
    const byId = Object.fromEntries(h.writes.map((w) => [w.id, w.patch]))
    expect(byId[A]).toHaveProperty('meeting_at')
    expect(byId[B]).not.toHaveProperty('meeting_at')
  })
})

describe('setDealValue', () => {
  it('writes the deal, the monthly retainer and its currency with the service role, never the amount to the timeline', async () => {
    const r = await setDealValue({ leadId: A, value: '150000', retainer: '1500', currency: 'USD' })
    expect(r.ok).toBe(true)
    expect(h.writes).toEqual([])
    expect(h.adminWrites).toEqual([{ table: 'leads', id: A, patch: { deal_value_inr: 150000, retainer_monthly_value: 1500, deal_currency: 'USD' } }])
    expect(h.activity).toEqual([[A, h.user.id, 'edit', { field: 'deal_value' }]])
  })

  it('leaves the retainer alone when the form sends only the deal value', async () => {
    await setDealValue({ leadId: A, value: '90000' })
    expect(h.adminWrites[0]?.patch).toEqual({ deal_value_inr: 90000 })
  })

  it('refuses a currency the database does not take', async () => {
    expect(await setDealValue({ leadId: A, value: '1', currency: 'EUR' })).toMatchObject({ ok: false, message: 'Choose a currency.' })
    expect(h.adminWrites).toEqual([])
  })
})
