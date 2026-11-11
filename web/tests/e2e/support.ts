import { expect, type Page } from '@playwright/test'
import { createClient } from '@supabase/supabase-js'
import type { Database } from '../../src/lib/database.types'

// Credentials come from the environment only. Nothing secret is written in the specs.
export const creds = {
  founder: { email: process.env.E2E_FOUNDER_EMAIL ?? '', password: process.env.E2E_FOUNDER_PASSWORD ?? '' },
  admin: { email: process.env.E2E_ADMIN_EMAIL ?? '', password: process.env.E2E_ADMIN_PASSWORD ?? '' },
}
export const hasFounder = Boolean(creds.founder.email && creds.founder.password)
export const hasAdmin = Boolean(creds.admin.email && creds.admin.password)
/** Creating a temporary caller is opt-in, so a run never adds people to a project by surprise. */
export const allowUserCreation = process.env.E2E_ALLOW_USER_CREATION === '1'

/** Service-role client for seeding and cleanup. Refuses to run against production. */
export function serviceClient() {
  if (process.env.APP_ENV === 'prod') throw new Error('End-to-end tests never run against production.')
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) throw new Error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are needed for seeding.')
  return createClient<Database>(url, key, { auth: { persistSession: false, autoRefreshToken: false } })
}

/** A browser-free client signed in as a user, to check what the database lets that user read. */
export async function userClient(email: string, password: string) {
  const sb = createClient<Database>(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
  const { error } = await sb.auth.signInWithPassword({ email, password })
  if (error) throw error
  return sb
}

export async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

export const GOOD_MESSAGE =
  'Hi Test Owner, saw your clinic is hiring a receptionist to handle calls and bookings. We are Nument, a small team that sets up WhatsApp booking replies so patients get answers even when the desk is busy. Would a short look at how it works be useful?'

export type Seeded = { runId: string; businessIds: string[]; leadIds: Record<'new1' | 'new2' | 'contacted' | 'talking' | 'proposal', string>; phones: string[] }

/** Five clearly marked test leads (2 new, 3 on the pipeline, one with a deal value), as in plan 15.10.2. */
export async function seed(): Promise<Seeded> {
  const sb = serviceClient()
  const runId = Date.now().toString(36)
  const now = Date.now()
  const day = 86_400_000
  const plan = [
    { key: 'new1', stage: 'new', grade: 'A' },
    { key: 'new2', stage: 'new', grade: 'B' },
    { key: 'contacted', stage: 'contacted', grade: 'A' },
    { key: 'talking', stage: 'talking', grade: 'A' },
    { key: 'proposal', stage: 'proposal_sent', grade: 'B' },
  ] as const
  const businessIds: string[] = []
  const phones: string[] = []
  const leadIds = {} as Seeded['leadIds']
  for (const [i, p] of plan.entries()) {
    const n = i + 1
    const name = `E2E Test Clinic ${n} ${runId}`
    const { data: b, error: be } = await sb
      .from('businesses')
      .insert({ segment_id: 'clinics-in', name, norm_name: name.toLowerCase(), country: 'in', city: 'Pune', website: `https://e2e-${runId}-${n}.example.com`, web_domain: `e2e-${runId}-${n}.example.com`, status: 'qualified' })
      .select('id')
      .single()
    if (be) throw be
    businessIds.push(b.id)
    // Never contacted: the specs use Mark sent, not the WhatsApp links.
    const phone = `+919000${String(10000 + Math.floor(Math.random() * 89999))}${n}`
    phones.push(phone)
    const inserts = await Promise.all([
      sb.from('contacts').insert({ business_id: b.id, name: `Test Owner ${n}`, role: 'Owner', phone_e164: phone, phone_type: 'mobile', source: 'website', is_decision_maker: true, verified: true }),
      sb.from('signals').insert({
        business_id: b.id,
        type: 'hiring_frontdesk',
        category: 'visible_pain',
        points: 8,
        observed_at: new Date(now - 4 * day).toISOString(),
        expires_at: new Date(now + 26 * day).toISOString(),
        source: 'e2e',
        url: 'https://example.com/e2e-signal',
        quote: 'Hiring a front desk executive',
        dedupe_key: `e2e:${runId}:${n}`,
      }),
    ])
    for (const r of inserts) if (r.error) throw r.error
    const { data: s, error: se } = await sb
      .from('scores')
      .insert({ business_id: b.id, version: 'e2e', fit: 3, can_pay: 20, intent: 30, reach: 1, total: p.grade === 'A' ? 82 : 61, grade: p.grade, pitch_mode: 'visible_pain', reasons: { fit: ['branches_count=2 (e2e)'], intent: [{ type: 'hiring_frontdesk', value: 8 }] } })
      .select('id')
      .single()
    if (se) throw se
    const { data: l, error: le } = await sb
      .from('leads')
      .insert({
        business_id: b.id,
        segment_id: 'clinics-in',
        score_id: s.id,
        grade: p.grade,
        pitch_mode: 'visible_pain',
        test_group: 'clinics-in:visible_pain:missed_calls',
        angle: 'missed_calls',
        message: GOOD_MESSAGE,
        followup_d3: 'Hello again, just checking whether you saw my note about WhatsApp booking replies for the clinic?',
        followup_d7: 'Last note from me. Happy to share a two minute demo if useful?',
        stage: p.stage,
        wa_at: p.stage === 'new' ? null : new Date(now - 4 * day).toISOString().slice(0, 10),
        deal_value_inr: p.key === 'proposal' ? 150000 : null,
      })
      .select('id')
      .single()
    if (le) throw le
    leadIds[p.key] = l.id
  }
  return { runId, businessIds, leadIds, phones }
}

export async function cleanup(s: Seeded | undefined) {
  if (!s) return
  const sb = serviceClient()
  await sb.from('leads').delete().in('id', Object.values(s.leadIds))
  await sb.from('businesses').delete().in('id', s.businessIds)
  await sb.from('suppression').delete().in('phone_e164', s.phones)
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}
