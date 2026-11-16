import { beforeEach, describe, expect, it, vi } from 'vitest'

// The new design's Settings, Engine and Insights pages: the one new Server Action (pause or resume sending) run
// against a stand-in for Supabase, and the pure helpers behind their rows, bars and filters.

const h = vi.hoisted(() => ({
  role: 'admin' as string,
  rows: [{ key: 'outreach.paused', value: false }] as { key: string; value: unknown }[],
  writes: [] as { table: string; patch: unknown; key: unknown }[],
  error: null as null | { code: string },
  verified: [] as unknown[],
}))

vi.mock('server-only', () => ({}))
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }))
vi.mock('@/lib/auth', () => ({
  requireRole: vi.fn(async (roles: string[], opts: unknown) => {
    h.verified.push(opts)
    // The real helper redirects (throws) when the role does not match.
    if (!roles.includes(h.role)) throw new Error('NEXT_REDIRECT')
    return { id: '00000000-0000-4000-8000-0000000000aa', role: h.role }
  }),
}))
vi.mock('@/lib/supabase/server', () => ({
  createClient: vi.fn(async () => ({
    from(table: string) {
      let patch: unknown
      let key: unknown
      const q = {
        update: (p: unknown) => ((patch = p), q),
        eq: (_c: string, v: unknown) => ((key = v), q),
        select: async () => {
          if (h.error) return { data: null, error: h.error }
          h.writes.push({ table, patch, key })
          const hit = h.rows.filter((r) => r.key === key)
          hit.forEach((r) => (r.value = patch && typeof patch === 'object' ? (patch as { value: unknown }).value : r.value))
          return { data: hit.map((r) => ({ key: r.key })), error: null }
        },
      }
      return q
    },
  })),
}))

const { setOutreachPaused } = await import('@/app/(v2)/v2/settings/actions')
const { MODE_LABEL, mailboxHealth, toMailbox, toSendingSettings, warmupState } = await import('@/app/(v2)/v2/settings/sending')
const { recipientSummary, suppressionCounts, suppressionInput } = await import('@/app/(v2)/v2/settings/summary')
const { runDuration, runResult, runStatus, sourceHealth } = await import('@/app/(v2)/v2/engine/labels')
const { barShare, insightsHref, parseInsightsQuery, pct } = await import('@/app/(v2)/v2/insights/filters')

beforeEach(() => {
  h.role = 'admin'
  h.rows = [{ key: 'outreach.paused', value: false }]
  h.writes.length = 0
  h.verified.length = 0
  h.error = null
})

describe('setOutreachPaused', () => {
  it('pauses and resumes all sending for an admin, checking the role with the Auth server', async () => {
    expect(await setOutreachPaused({ paused: true })).toEqual({ ok: true, message: 'All sending paused', data: undefined })
    expect(h.rows[0]!.value).toBe(true)
    expect(h.writes).toEqual([{ table: 'settings', patch: { value: true }, key: 'outreach.paused' }])
    expect(h.verified[0]).toEqual({ verified: true })
    expect((await setOutreachPaused({ paused: false })).message).toBe('Sending resumed')
    expect(h.rows[0]!.value).toBe(false)
  })

  it('is admin only', async () => {
    h.role = 'caller'
    await expect(setOutreachPaused({ paused: true })).rejects.toThrow('NEXT_REDIRECT')
    expect(h.writes).toEqual([])
  })

  it('rejects anything but a boolean', async () => {
    const r = await setOutreachPaused({ paused: 'yes' } as unknown as { paused: boolean })
    expect(r.ok).toBe(false)
    expect(h.writes).toEqual([])
  })

  it('says so when the setting is missing or the save fails', async () => {
    h.rows = []
    expect(await setOutreachPaused({ paused: true })).toMatchObject({ ok: false, message: expect.stringContaining('not set up') })
    h.error = { code: '42501' }
    expect(await setOutreachPaused({ paused: true })).toMatchObject({ ok: false, message: 'Could not save. Try again.' })
  })
})

describe('sending settings and the mailbox', () => {
  it('reads the outreach settings with safe defaults', () => {
    expect(toSendingSettings([])).toEqual({ mode: 'off', paused: false, warmup: [10, 15, 20, 25, 30, 35, 40], bouncePausePct: null })
    expect(
      toSendingSettings([
        { key: 'outreach.mode', value: 'auto' },
        { key: 'outreach.paused', value: true },
        { key: 'outreach.warmup', value: [5, '10', 'x', -1, 20] },
        { key: 'outreach.bounce_pause_pct', value: 3 },
      ]),
    ).toEqual({ mode: 'auto', paused: true, warmup: [5, 10, 20], bouncePausePct: 3 })
    expect(toSendingSettings([{ key: 'outreach.mode', value: 'everything' }]).mode).toBe('off')
    expect(MODE_LABEL.manual).toBe('You approve every email')
  })

  it('follows the engine warm-up: one cap per week since the first send, the last one holds', () => {
    const box = { warmup_started_on: '2026-11-01', sent_today: 12, sent_day: '2026-11-16' }
    const caps = [10, 15, 20]
    expect(warmupState(box, caps, '2026-11-01')).toMatchObject({ week: 1, capNow: 10, done: false, sentToday: 0 })
    expect(warmupState(box, caps, '2026-11-08')).toMatchObject({ week: 2, capNow: 15, done: false })
    expect(warmupState(box, caps, '2026-11-16')).toMatchObject({ week: 3, weeks: 3, capNow: 20, capEnd: 20, done: true, sentToday: 12 })
    expect(warmupState(box, caps, '2026-12-30')).toMatchObject({ capNow: 20, done: true })
    expect(warmupState(box, caps, '2026-10-30')).toMatchObject({ week: 0, capNow: 0 })
    expect(warmupState({ warmup_started_on: null, sent_today: 0, sent_day: null }, caps, '2026-11-16')).toMatchObject({ week: 1, capNow: 10, started: false, done: false })
  })

  it('checks mailbox rows and describes their health in a few words', () => {
    expect(toMailbox({ id: 1 })).toBeNull()
    const box = toMailbox({ id: 'm1', email: 'hello@nument.in', status: 'warming', sent_today: '4' })!
    expect(box).toMatchObject({ display_name: 'Nument', status: 'warming', sent_today: 4, paused_reason: null })
    expect(toMailbox({ id: 'm2', email: 'a@b.c', status: 'strange' })!.status).toBe('disconnected')

    expect(mailboxHealth(null, { bounced: 0, sent: 0 }, false)).toEqual({ tone: 'none', label: 'No mailbox connected' })
    expect(mailboxHealth(box, { bounced: 0, sent: 0 }, false)).toEqual({ tone: 'ok', label: 'Good · Nothing sent yet' })
    expect(mailboxHealth(box, { bounced: 1, sent: 40 }, false).label).toBe('Good · 2.5% bounced of the last 40')
    expect(mailboxHealth(box, { bounced: 0, sent: 10 }, true)).toMatchObject({ tone: 'warn', label: 'Sending paused · 0% bounced of the last 10' })
    expect(mailboxHealth({ ...box, status: 'paused', paused_reason: 'bounce_rate' }, { bounced: 4, sent: 100 }, false)).toEqual({
      tone: 'warn',
      label: 'Paused: too many emails bounced · 4% bounced of the last 100',
    })
    expect(mailboxHealth({ ...box, status: 'error', last_error: 'invalid_grant' }, { bounced: 0, sent: 0 }, false)).toEqual({ tone: 'bad', label: 'Error · invalid_grant' })
  })
})

describe('settings rows', () => {
  it('sums up what a recipient gets', () => {
    expect(recipientSummary({ morning: true, alerts: false, weekly: true, active: true })).toBe('Morning list, Weekly report')
    expect(recipientSummary({ morning: false, alerts: false, weekly: false, active: true })).toBe('Gets no email')
    expect(recipientSummary({ morning: true, alerts: true, weekly: true, active: false })).toBe('Paused: gets no email')
  })

  it('counts Do not contact entries and rebuilds one for Undo', () => {
    const e = (over: Partial<{ phone_e164: string; email: string; web_domain: string }>) => ({ id: 'x', phone_e164: null, email: null, web_domain: null, reason: 'opt_out', ...over })
    expect(suppressionCounts([])).toBe('Nobody yet')
    expect(suppressionCounts([e({ email: 'a@b.co' })])).toBe('1 email')
    expect(suppressionCounts([e({ email: 'a@b.co' }), e({ email: 'c@d.co' }), e({ phone_e164: '+919800000001' }), e({ web_domain: 'x.com' })])).toBe('2 emails, 1 phone and 1 website')
    expect(suppressionInput(e({ phone_e164: '+919800000001' }))).toEqual({ kind: 'phone', value: '+919800000001' })
    expect(suppressionInput(e({ web_domain: 'x.com' }))).toEqual({ kind: 'domain', value: 'x.com' })
    expect(suppressionInput(e({}))).toBeNull()
  })
})

describe('engine labels', () => {
  it('words runs and sources plainly', () => {
    expect(runStatus('ok')).toEqual({ tone: 'ok', label: 'Done' })
    expect(runStatus('failed').tone).toBe('bad')
    expect(runStatus('odd')).toEqual({ tone: 'none', label: 'odd' })
    expect(sourceHealth('blocked')).toEqual({ tone: 'bad', label: 'Blocked' })
    expect(sourceHealth(null)).toEqual({ tone: 'none', label: 'Unknown' })
    expect(runDuration('2026-11-16T00:00:00Z', null)).toBe('')
    expect(runDuration('2026-11-16T00:00:00Z', '2026-11-16T00:00:20Z')).toBe('under a minute')
    expect(runDuration('2026-11-16T00:00:00Z', '2026-11-16T01:05:00Z')).toBe('1 h 5 min')
    expect(runResult({ researched: 1200, leads: 1, cost_inr: 82 }, (n) => `Rs ${n}`)).toBe('1,200 researched · 1 lead · Rs 82')
    expect(runResult(null, String)).toBe('')
  })
})

describe('insights filters and bars', () => {
  it('reads the period, segment, country and grouping, defaulting safely', () => {
    expect(parseInsightsQuery({}, '2026-11-16')).toEqual({ period: '30', from: '2026-10-18', to: '2026-11-16', seg: '', country: '', group: 'segment' })
    expect(parseInsightsQuery({ days: '7', seg: 'clinics-in', country: 'ae', group: 'signal' }, '2026-11-16')).toMatchObject({
      period: '7',
      from: '2026-11-10',
      seg: 'clinics-in',
      country: 'ae',
      group: 'signal',
    })
    expect(parseInsightsQuery({ days: '365', seg: 'DROP TABLE', country: 'india', group: 'money' }, '2026-11-16')).toMatchObject({ period: '30', seg: '', country: '', group: 'segment' })
  })

  it('writes the address bar back without defaults', () => {
    expect(insightsHref({ period: '30', seg: '', country: '', group: 'segment' })).toBe('/insights')
    expect(insightsHref({ period: '90', seg: 'x', country: 'in', group: 'pitch' })).toBe('/insights?days=90&seg=x&country=in&group=pitch')
  })

  it('sizes bars and rates', () => {
    expect(barShare(0, 10)).toBe(0)
    expect(barShare(5, 0)).toBe(0)
    expect(barShare(5, 10)).toBe(0.5)
    expect(barShare(1, 10_000)).toBe(0.02)
    expect(barShare(20, 10)).toBe(1)
    expect(pct(1, 3)).toBe('33%')
    expect(pct(1, 0)).toBe('')
  })
})
