// Ephemeral e2e fixtures. The Supabase project is dev and prod at once and holds real leads, so:
// every row a test may change is created here, carries a marker, and is deleted in teardown;
// test users are temporary; and a guard refuses to act on any lead that is not a fixture.
import { randomBytes } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { createClient } from '@supabase/supabase-js'
import type { Database } from '../../src/lib/database.types'

export const FIXTURE_PREFIX = 'E2E Fixture'
export const MARKER_KEY = 'e2e_fixture'
export const FIXTURE_EMAIL = /^e2e-[a-z]+-[a-z0-9]+@example\.com$/
/** Email recipients the specs add (Settings > Email recipients): reserved domain, so never mailed. */
export const RECIPIENT_PATTERN = 'e2e-%@example.com'
const RUN_FILE = path.join(__dirname, '.auth', 'run.json')

export type TestUser = { id: string; email: string; password: string }
export type LeadKey = 'new1' | 'new2' | 'contacted' | 'talking' | 'proposal'
export type Run = {
  runId: string
  /** The everyday test users. Their product tour is already done, so it never covers the page. */
  admin: TestUser
  caller: TestUser
  /** Fresh users for the tour specs: no tour yet, and one still on a temporary password. */
  tourAdmin: TestUser
  tourCaller: TestUser
  tourNew: TestUser
  businessIds: string[]
  leadIds: Record<LeadKey, string>
  names: Record<LeadKey, string>
  phones: string[]
}

export function serviceClient() {
  if (process.env.APP_ENV === 'prod') throw new Error('End-to-end tests never run with APP_ENV=prod.')
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) throw new Error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are needed for e2e fixtures.')
  return createClient<Database>(url, key, { auth: { persistSession: false, autoRefreshToken: false } })
}

/** A strong random password: every character class, kept in memory and in a gitignored 0600 file only. */
export const strongPassword = () => `Aa1!${randomBytes(18).toString('base64url')}`

export function saveRun(run: Run) {
  mkdirSync(path.dirname(RUN_FILE), { recursive: true })
  writeFileSync(RUN_FILE, JSON.stringify(run), { mode: 0o600 })
  chmodSync(RUN_FILE, 0o600)
}

export function readRun(): Run {
  if (!existsSync(RUN_FILE)) throw new Error('No e2e run file. globalSetup did not run.')
  return JSON.parse(readFileSync(RUN_FILE, 'utf8')) as Run
}

export const removeRunFile = () => rmSync(RUN_FILE, { force: true })

/** Refuses to continue unless the lead belongs to this run's fixtures. Call before every mutation. */
export async function assertFixtureLead(leadId: string, run: Run = readRun()) {
  const sb = serviceClient()
  const { data: lead } = await sb.from('leads').select('business_id').eq('id', leadId).maybeSingle()
  if (!lead) throw new Error(`Guard: lead ${leadId} not found.`)
  const { data: b } = await sb.from('businesses').select('name, extra').eq('id', lead.business_id).maybeSingle()
  const marker = (b?.extra as Record<string, unknown> | null)?.[MARKER_KEY]
  if (!b || !b.name.startsWith(FIXTURE_PREFIX) || marker !== run.runId) {
    throw new Error(`Guard: lead ${leadId} is not an e2e fixture of run ${run.runId}. Refusing to touch it.`)
  }
}

type UserPlan = { key: string; role: 'admin' | 'caller'; name: string; tourDone: boolean; mustChange?: boolean }

async function createUser(sb: ReturnType<typeof serviceClient>, plan: UserPlan, runId: string): Promise<TestUser> {
  const { key, role, name } = plan
  const email = `e2e-${key}-${runId}@example.com`
  const password = strongPassword()
  const { data, error } = await sb.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
    user_metadata: plan.tourDone ? { full_name: name, tour_completed_at: new Date().toISOString() } : { full_name: name },
    app_metadata: { must_change_password: Boolean(plan.mustChange) },
  })
  if (error || !data.user) throw new Error(`Could not create the ${role} test user (${error?.code ?? 'unknown'}).`)
  const { error: pe } = await sb.from('profiles').upsert({ user_id: data.user.id, full_name: name, role }, { onConflict: 'user_id' })
  if (pe) throw new Error(`Could not set the ${role} test role (${pe.code}).`)
  return { id: data.user.id, email, password }
}

export const GOOD_MESSAGE =
  'Hi Test Owner, saw your clinic is hiring a receptionist to handle calls and bookings. We are Nument, a small team that sets up WhatsApp booking replies so patients get answers even when the desk is busy. Would a short look at how it works be useful?'

/**
 * Five test users and five fixture leads (2 new, 3 on the pipeline, one with a deal value).
 * E2E_FIXTURE_LEADS=0 skips the leads, to see the app as it is with no leads at all.
 */
export async function createFixtures(): Promise<Run> {
  const sb = serviceClient()
  await deleteFixtures() // leftovers from an interrupted run, if any
  const runId = `${Date.now().toString(36)}${randomBytes(2).toString('hex')}`
  const admin = await createUser(sb, { key: 'admin', role: 'admin', name: 'E2E Admin', tourDone: true }, runId)
  const caller = await createUser(sb, { key: 'caller', role: 'caller', name: 'E2E Caller', tourDone: true }, runId)
  const tourAdmin = await createUser(sb, { key: 'touradmin', role: 'admin', name: 'E2E Tour Admin', tourDone: false }, runId)
  const tourCaller = await createUser(sb, { key: 'tourcaller', role: 'caller', name: 'E2E Tour Caller', tourDone: false }, runId)
  const tourNew = await createUser(sb, { key: 'tournew', role: 'caller', name: 'E2E Tour New', tourDone: false, mustChange: true }, runId)
  const withLeads = process.env.E2E_FIXTURE_LEADS !== '0'
  const now = Date.now()
  const day = 86_400_000
  const plan: { key: LeadKey; stage: string; grade: 'A' | 'B'; city: string }[] = [
    { key: 'new1', stage: 'new', grade: 'A', city: 'Pune' },
    { key: 'new2', stage: 'new', grade: 'B', city: 'Mumbai' },
    { key: 'contacted', stage: 'contacted', grade: 'A', city: 'Pune' },
    { key: 'talking', stage: 'talking', grade: 'A', city: 'Bengaluru' },
    { key: 'proposal', stage: 'proposal_sent', grade: 'B', city: 'Delhi' },
  ]
  const businessIds: string[] = []
  const phones: string[] = []
  const leadIds = {} as Run['leadIds']
  const names = {} as Run['names']
  for (const [i, p] of (withLeads ? plan : []).entries()) {
    const n = i + 1
    const name = `${FIXTURE_PREFIX} Clinic ${n} ${runId}`
    names[p.key] = name
    const { data: b, error: be } = await sb
      .from('businesses')
      .insert({
        segment_id: 'clinics-in',
        name,
        norm_name: name.toLowerCase(),
        country: 'in',
        city: p.city,
        website: `https://e2e-${runId}-${n}.example.com`,
        web_domain: `e2e-${runId}-${n}.example.com`,
        status: 'qualified',
        extra: { [MARKER_KEY]: runId },
      })
      .select('id')
      .single()
    if (be) throw be
    businessIds.push(b.id)
    // Never contacted: the specs use Mark sent, never the WhatsApp links.
    const phone = `+919000${String(10000 + Math.floor(Math.random() * 89999))}${n}`
    phones.push(phone)
    const inserts = await Promise.all([
      sb.from('contacts').insert({ business_id: b.id, name: `Test Owner ${n}`, role: 'Owner', phone_e164: phone, phone_type: 'mobile', source: 'website', source_url: `https://e2e-${runId}-${n}.example.com/contact`, is_decision_maker: true, verified: true }),
      sb.from('signals').insert({
        business_id: b.id,
        type: 'hiring_frontdesk',
        category: 'visible_pain',
        points: 8,
        observed_at: new Date(now - (n + 2) * day).toISOString(),
        expires_at: new Date(now + 26 * day).toISOString(),
        source: 'e2e',
        url: 'https://example.com/e2e-signal',
        quote: 'Hiring a front desk executive to manage patient calls',
        dedupe_key: `e2e:${runId}:${n}`,
      }),
      sb.from('facts').insert([
        { business_id: b.id, field: 'branches', value: 2, quote: 'Two branches in the city', url: `https://e2e-${runId}-${n}.example.com/about`, model: 'e2e', verified: true },
        { business_id: b.id, field: 'booking_method', value: 'phone only', quote: 'Call us to book an appointment', url: `https://e2e-${runId}-${n}.example.com`, model: 'rule', verified: true },
        { business_id: b.id, field: 'whatsapp_present', value: false, quote: null, url: `https://e2e-${runId}-${n}.example.com`, model: 'rule', verified: true },
      ]),
    ])
    for (const r of inserts) if (r.error) throw r.error
    const { data: s, error: se } = await sb
      .from('scores')
      .insert({
        business_id: b.id,
        version: 'e2e',
        fit: 3,
        can_pay: p.grade === 'A' ? 22 : 15,
        intent: p.grade === 'A' ? 30 : 22,
        reach: 1,
        total: p.grade === 'A' ? 82 : 61,
        grade: p.grade,
        pitch_mode: 'visible_pain',
        reasons: { fit: ['branches_count=2 (fixture)'], can_pay: ['review_count=140 (fixture)'], intent: [{ type: 'hiring_frontdesk', value: 8 }], reach: ['mobile from own website'] },
        judge_note: 'Fixture lead for end-to-end tests. Hiring front desk staff with two branches and phone-only booking.',
        judge_model: 'e2e-fixture',
      })
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
        message_alt: GOOD_MESSAGE.replace('Would a short look at how it works be useful?', 'Could I share a two minute example of how it works?'),
        followup_d3: 'Hello again, just checking whether you saw my note about WhatsApp booking replies for the clinic?',
        followup_d7: 'Last note from me. Happy to share a short demo if that would help?',
        stage: p.stage,
        wa_at: p.stage === 'new' ? null : new Date(now - 4 * day).toISOString().slice(0, 10),
        next_step: p.stage === 'talking' ? 'Book discovery call' : p.stage === 'proposal_sent' ? 'Follow up proposal' : null,
        due_at: p.stage === 'talking' ? new Date(now - day).toISOString().slice(0, 10) : p.stage === 'proposal_sent' ? new Date(now + 2 * day).toISOString().slice(0, 10) : null,
        deal_value_inr: p.key === 'proposal' ? 150000 : null,
        notes: p.key === 'talking' ? 'Owner asked for a call after 5 pm.' : null,
      })
      .select('id')
      .single()
    if (le) throw le
    leadIds[p.key] = l.id
  }
  const run: Run = { runId, admin, caller, tourAdmin, tourCaller, tourNew, businessIds, leadIds, names, phones }
  saveRun(run)
  return run
}

/** Every fixture row and test user, found by marker (not only by this run), so nothing is left behind. */
export async function deleteFixtures() {
  const sb = serviceClient()
  const { data: businesses } = await sb.from('businesses').select('id, name, extra').like('name', `${FIXTURE_PREFIX}%`)
  const marked = (businesses ?? []).filter((b) => (b.extra as Record<string, unknown> | null)?.[MARKER_KEY])
  const ids = marked.map((b) => b.id)
  if (ids.length) {
    const { data: leads } = await sb.from('leads').select('id').in('business_id', ids)
    const leadIds = (leads ?? []).map((l) => l.id)
    if (leadIds.length) {
      for (const id of leadIds) {
        const { data: files } = await sb.storage.from('proposals').list(id)
        if (files?.length) await sb.storage.from('proposals').remove(files.map((f) => `${id}/${f.name}`))
      }
      const { error } = await sb.from('leads').delete().in('id', leadIds) // activities, feedback cascade
      if (error) throw error
    }
    const { data: contacts } = await sb.from('contacts').select('phone_e164').in('business_id', ids)
    const phones = (contacts ?? []).map((c) => c.phone_e164).filter((p): p is string => Boolean(p))
    if (phones.length) await sb.from('suppression').delete().in('phone_e164', phones)
    const { error } = await sb.from('businesses').delete().in('id', ids) // contacts, signals, facts, scores cascade
    if (error) throw error
  }
  await sb.from('inbox_posts').delete().like('text', `${FIXTURE_PREFIX}%`)
  await sb.from('custom_queries').delete().like('query', `${FIXTURE_PREFIX}%`)
  await sb.from('notify_recipients').delete().like('email', RECIPIENT_PATTERN)
  const { data: list } = await sb.auth.admin.listUsers({ page: 1, perPage: 1000 })
  for (const u of list?.users ?? []) {
    if (u.email && FIXTURE_EMAIL.test(u.email)) {
      const { error } = await sb.auth.admin.deleteUser(u.id)
      if (error) throw new Error(`Could not delete test user ${u.email} (${error.code}).`)
    }
  }
}

/** Counts of anything an e2e run could have left. All must be zero. */
export async function leftovers() {
  const sb = serviceClient()
  const head = { count: 'exact' as const, head: true }
  const { data: businesses } = await sb.from('businesses').select('id').like('name', `${FIXTURE_PREFIX}%`)
  const ids = (businesses ?? []).map((b) => b.id)
  const none = ['00000000-0000-0000-0000-000000000000']
  const [leads, contacts, signals, scores, facts, inbox, queries, markedBusinesses, recipients] = await Promise.all([
    sb.from('leads').select('id', head).in('business_id', ids.length ? ids : none),
    sb.from('contacts').select('id', head).in('business_id', ids.length ? ids : none),
    sb.from('signals').select('id', head).like('dedupe_key', 'e2e:%'),
    sb.from('scores').select('id', head).eq('version', 'e2e'),
    sb.from('facts').select('id', head).in('business_id', ids.length ? ids : none),
    sb.from('inbox_posts').select('id', head).like('text', `${FIXTURE_PREFIX}%`),
    sb.from('custom_queries').select('id', head).like('query', `${FIXTURE_PREFIX}%`),
    sb.from('businesses').select('id', head).not(`extra->>${MARKER_KEY}`, 'is', null),
    sb.from('notify_recipients').select('id', head).like('email', RECIPIENT_PATTERN),
  ])
  const { data: list } = await sb.auth.admin.listUsers({ page: 1, perPage: 1000 })
  return {
    businesses: ids.length,
    markedBusinesses: markedBusinesses.count ?? 0,
    leads: leads.count ?? 0,
    contacts: contacts.count ?? 0,
    signals: signals.count ?? 0,
    scores: scores.count ?? 0,
    facts: facts.count ?? 0,
    inboxPosts: inbox.count ?? 0,
    customQueries: queries.count ?? 0,
    emailRecipients: recipients.count ?? 0,
    testUsers: (list?.users ?? []).filter((u) => u.email && FIXTURE_EMAIL.test(u.email)).length,
  }
}
