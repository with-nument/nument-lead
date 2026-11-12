import { describe, expect, it } from 'vitest'
import {
  LEAD_ROUTE,
  TOUR_STEPS,
  completedAtOf,
  isLeadPath,
  needsNavigation,
  pickLeadPath,
  placeCard,
  routeOf,
  shouldAutoStart,
  stepText,
  tourStepsFor,
  tourStorageKey,
} from '@/lib/tour'

const LEAD = '/leads/0f8fad5b-d9cb-469f-a165-70867728950e'
const ids = (role: 'admin' | 'caller' | 'viewer') => tourStepsFor(role).map((s) => s.id)

describe('tourStepsFor', () => {
  it('gives admins every page, including Engine, Inbox, users, Do not contact and the deal card', () => {
    expect(ids('admin')).toEqual(TOUR_STEPS.map((s) => s.id))
    for (const id of ['engine-budget', 'engine-sources', 'inbox', 'users', 'do-not-contact', 'lead-deal']) expect(ids('admin')).toContain(id)
  })

  it('leaves out pages a caller cannot open, and never shows a caller the money card', () => {
    const caller = ids('caller')
    for (const id of ['engine-budget', 'engine-sources', 'inbox', 'users', 'do-not-contact', 'lead-deal']) expect(caller).not.toContain(id)
    for (const id of ['welcome', 'today-send-list', 'today-whatsapp', 'leads-filters', 'lead-why', 'pipeline', 'insights', 'settings', 'done']) expect(caller).toContain(id)
  })

  it('gives viewers no send step, since they cannot send', () => {
    expect(ids('viewer')).not.toContain('today-whatsapp')
    expect(ids('viewer')).toContain('today-send-list')
  })

  it('starts with the welcome and ends on the replay button for everyone', () => {
    for (const role of ['admin', 'caller', 'viewer'] as const) {
      const steps = tourStepsFor(role)
      expect(steps[0]?.id).toBe('welcome')
      expect(steps.at(-1)?.id).toBe('done')
      expect(steps.at(-1)?.target).toEqual(['tour-button'])
    }
  })

  it('uses role words where they differ and never mentions money or owners to a caller', () => {
    const admin = tourStepsFor('admin').find((s) => s.id === 'lead-stage')
    const caller = tourStepsFor('caller').find((s) => s.id === 'lead-stage')
    expect(admin?.title).toBe('Stage, owner and next step')
    expect(caller?.title).toBe('Stage and next step')
    const callerCopy = tourStepsFor('caller').map((s) => `${s.title} ${s.body} ${s.fallback ?? ''}`).join(' ')
    expect(callerCopy).not.toMatch(/won this month|what they cost|owns it/)
  })

  it('drops the role fields from the result', () => {
    for (const s of tourStepsFor('admin')) {
      expect(s).not.toHaveProperty('forRole')
      expect(s).not.toHaveProperty('roles')
    }
  })
})

describe('tour copy', () => {
  const all = TOUR_STEPS.flatMap((s) => [s.title, s.body, s.fallback ?? '', ...Object.values(s.forRole ?? {}).flatMap((c) => [c.title ?? '', c.body ?? '', c.fallback ?? ''])])

  it('has no em or en dashes and no spaced hyphens', () => {
    for (const text of all) {
      expect(text).not.toMatch(/[‒–—―]/)
      expect(text).not.toMatch(/\s-\s/)
    }
  })

  it('stays short enough to read at a glance', () => {
    for (const s of TOUR_STEPS) {
      expect(s.title.length).toBeLessThanOrEqual(32)
      expect(s.body.length).toBeLessThanOrEqual(240)
      expect((s.fallback ?? '').length).toBeLessThanOrEqual(240)
    }
  })

  it('has unique ids and a fallback-safe body for every step', () => {
    expect(new Set(TOUR_STEPS.map((s) => s.id)).size).toBe(TOUR_STEPS.length)
    for (const s of TOUR_STEPS) expect(s.body.trim()).not.toBe('')
  })

  it('puts every lead page step on the lead route', () => {
    for (const s of TOUR_STEPS.filter((x) => x.id.startsWith('lead-'))) expect(s.route).toBe(LEAD_ROUTE)
  })
})

describe('stepText', () => {
  it('uses the fallback only when the highlighted part is missing', () => {
    const step = { body: 'Here it is.', fallback: 'It shows up here later.' }
    expect(stepText(step, true)).toBe('Here it is.')
    expect(stepText(step, false)).toBe('It shows up here later.')
    expect(stepText({ body: 'Same words.' }, false)).toBe('Same words.')
  })
})

describe('completedAtOf and shouldAutoStart', () => {
  it('only trusts a real date string', () => {
    expect(completedAtOf({ tour_completed_at: '2026-11-12T05:00:00.000Z' })).toBe('2026-11-12T05:00:00.000Z')
    expect(completedAtOf({ tour_completed_at: 'yes' })).toBeNull()
    expect(completedAtOf({ tour_completed_at: true })).toBeNull()
    expect(completedAtOf({})).toBeNull()
    expect(completedAtOf(null)).toBeNull()
  })

  it('starts once, after the forced password change, and never again', () => {
    expect(shouldAutoStart({ mustChangePassword: false, completedAt: null, doneLocally: false })).toBe(true)
    expect(shouldAutoStart({ mustChangePassword: true, completedAt: null, doneLocally: false })).toBe(false)
    expect(shouldAutoStart({ mustChangePassword: false, completedAt: '2026-11-12T05:00:00.000Z', doneLocally: false })).toBe(false)
    expect(shouldAutoStart({ mustChangePassword: false, completedAt: null, doneLocally: true })).toBe(false)
  })

  it('keeps the local mirror per user', () => {
    expect(tourStorageKey('a')).not.toBe(tourStorageKey('b'))
  })
})

describe('lead page and routes', () => {
  it('recognises lead pages only', () => {
    expect(isLeadPath(LEAD)).toBe(true)
    expect(isLeadPath('/leads')).toBe(false)
    expect(isLeadPath('/leads/export')).toBe(false)
    expect(isLeadPath(`${LEAD}/extra`)).toBe(false)
  })

  it('keeps the open lead, else takes the first lead link, else none', () => {
    expect(pickLeadPath(LEAD, ['/leads/11111111-1111-4111-8111-111111111111'])).toBe(LEAD)
    expect(pickLeadPath('/leads', ['/leads/export?grade=A', `${LEAD}?unverified=1`])).toBe(LEAD)
    expect(pickLeadPath('/leads', ['/leads/export', '/pipeline'])).toBeNull()
    expect(pickLeadPath('/', [])).toBeNull()
  })

  it('resolves the lead route, and stays put without a lead', () => {
    expect(routeOf({ route: LEAD_ROUTE }, LEAD)).toBe(LEAD)
    expect(routeOf({ route: LEAD_ROUTE }, null)).toBeNull()
    expect(routeOf({ route: '/pipeline' }, null)).toBe('/pipeline')
    expect(routeOf({}, LEAD)).toBeNull()
  })

  it('navigates only when the page differs', () => {
    expect(needsNavigation('/leads', '/leads')).toBe(false)
    expect(needsNavigation('/', '/leads')).toBe(true)
    expect(needsNavigation('/leads', null)).toBe(false)
  })
})

describe('placeCard', () => {
  const desk = { width: 1440, height: 900 }
  const phone = { width: 390, height: 844 }
  const card = { width: 360, height: 200 }

  it('centres the card when there is nothing to point at', () => {
    const p = placeCard(null, card, desk)
    expect(p.side).toBe('center')
    expect(p.left).toBe((1440 - 360) / 2)
    expect(p.top).toBe((900 - 200) / 2)
  })

  it('goes below a target with room, aligned to its left edge', () => {
    const p = placeCard({ top: 100, left: 300, width: 400, height: 120 }, card, desk)
    expect(p).toMatchObject({ side: 'bottom', left: 300, top: 100 + 120 + 14 })
  })

  it('goes above when there is no room below', () => {
    const p = placeCard({ top: 600, left: 300, width: 400, height: 200 }, card, desk)
    expect(p.side).toBe('top')
    expect(p.top + 200).toBeLessThanOrEqual(600)
  })

  it('goes beside a tall target, and docks when nothing fits', () => {
    expect(placeCard({ top: 80, left: 260, width: 700, height: 800 }, card, desk).side).toBe('right')
    expect(placeCard({ top: 80, left: 20, width: 1400, height: 800 }, card, desk).side).toBe('dock-bottom')
  })

  it('never leaves the window', () => {
    const p = placeCard({ top: 100, left: 1400, width: 30, height: 30 }, card, desk)
    expect(p.left + p.width).toBeLessThanOrEqual(1440 - 16)
    expect(p.left).toBeGreaterThanOrEqual(16)
  })

  it('docks full width on phones, away from the highlight', () => {
    const low = placeCard({ top: 600, left: 16, width: 358, height: 120 }, card, phone)
    expect(low).toMatchObject({ side: 'dock-top', left: 16, width: 390 - 32, top: 16 })
    const high = placeCard({ top: 80, left: 16, width: 358, height: 120 }, card, phone)
    expect(high).toMatchObject({ side: 'dock-bottom', width: 390 - 32, top: 844 - 200 - 16 })
  })
})
