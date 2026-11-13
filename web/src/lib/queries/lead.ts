import 'server-only'
import { createClient, type ServerClient } from '@/lib/supabase/server'
import { getMoney } from './leads'

const LEAD_COLUMNS =
  'id, business_id, segment_id, score_id, grade, pitch_mode, test_group, angle, channel, message, message_alt, email_subject, email_body, followup_d3, followup_d7, message_model, message_check_score, stage, owner_id, wa_at, call_at, d3_at, d7_at, meeting_at, next_step, due_at, skipped_until, regen_requested_at, notes, created_at, updated_at, last_activity_at, name, city, locality, country, website, web_domain, category, subcategory, total, judge_note, top_signal_type, top_signal_quote, top_signal_url, top_signal_at, contact_name, contact_role, phone_e164, phone_type, phone_source, email' as const

const BUSINESS_COLUMNS = 'name, website, web_domain, address, place_id, branches_count, staff_count, rating, review_count'
const CONTACT_COLUMNS =
  'id, name, role, phone_e164, phone_type, email, source, source_url, quote, is_decision_maker, verified, do_not_contact, created_at'
const SIGNAL_COLUMNS = 'id, type, category, points, observed_at, expires_at, source, url, quote'
const FACT_COLUMNS = 'id, field, value, quote, url, model, verified, created_at'
const SCORE_COLUMNS = 'fit, can_pay, intent, reach, total, grade, pitch_mode, reasons, judge_grade, judge_note, judge_model, version, computed_at'
const PAGE_COLUMNS = 'id, url, title, fetched_at'

/**
 * The lead's business with its contacts, signals, facts, latest score and pages, in one request:
 * PostgREST embeds them through the foreign keys, keyed on the lead id, so nothing waits for the
 * business id first. Row Level Security applies to every embedded table as it does to a direct read.
 * The hints pick the direct business_id link (leads and facts also join businesses to scores and pages).
 */
function businessEvidence(sb: ServerClient, leadId: string, includeUnverified: boolean) {
  let q = sb
    .from('leads')
    .select(
      `business_id, lost_reason, business:businesses!leads_business_id_fkey!inner(${BUSINESS_COLUMNS},
        contacts:contacts!contacts_business_id_fkey(${CONTACT_COLUMNS}),
        signals:signals!signals_business_id_fkey(${SIGNAL_COLUMNS}),
        facts:facts!facts_business_id_fkey(${FACT_COLUMNS}),
        scores:scores!scores_business_id_fkey(${SCORE_COLUMNS}),
        pages:pages!pages_business_id_fkey(${PAGE_COLUMNS}))`,
    )
    .eq('id', leadId)
    .order('is_decision_maker', { referencedTable: 'business.contacts', ascending: false })
    .order('created_at', { referencedTable: 'business.contacts', ascending: true })
    .limit(50, { referencedTable: 'business.contacts' })
    .order('observed_at', { referencedTable: 'business.signals', ascending: false })
    .limit(50, { referencedTable: 'business.signals' })
    .order('created_at', { referencedTable: 'business.facts', ascending: false })
    .limit(300, { referencedTable: 'business.facts' })
    .order('computed_at', { referencedTable: 'business.scores', ascending: false })
    .limit(1, { referencedTable: 'business.scores' })
    .order('fetched_at', { referencedTable: 'business.pages', ascending: false })
    .limit(20, { referencedTable: 'business.pages' })
  if (!includeUnverified) q = q.eq('business.facts.verified', true)
  return q.maybeSingle()
}

/**
 * Everything the lead page shows, in two rounds: the lead, its business evidence, activities and
 * feedback together, then the Do not contact check for the contacts' phones. Returns null when the
 * lead is not visible to this user. Runs as the user and never reads money: admins get the deal value
 * and retainer with `getLeadMoney` after the role check.
 */
export async function getLeadDetail(leadId: string, opts: { includeUnverified: boolean }) {
  const sb = await createClient()
  const [view, evidence, activities, feedback] = await Promise.all([
    sb.from('v_leads_caller').select(LEAD_COLUMNS).eq('id', leadId).maybeSingle(),
    businessEvidence(sb, leadId, opts.includeUnverified),
    sb.from('activities').select('id, type, source, at, user_id, payload').eq('lead_id', leadId).order('at', { ascending: false }).limit(100),
    sb.from('feedback').select('id, user_id, rating, reason, at').eq('lead_id', leadId).order('at', { ascending: false }),
  ])
  if (view.error) throw view.error
  const row = view.data
  if (!row?.id || !row.business_id) return null
  const businessId = row.business_id
  for (const r of [evidence, activities, feedback]) if (r.error) throw r.error
  const found = evidence.data?.business_id === businessId ? evidence.data.business : null
  const contacts = found?.contacts ?? []
  const signals = found?.signals ?? []
  const facts = found?.facts ?? []
  const pages = found?.pages ?? []
  const business = found
    ? {
        name: found.name,
        website: found.website,
        web_domain: found.web_domain,
        address: found.address,
        place_id: found.place_id,
        branches_count: found.branches_count,
        staff_count: found.staff_count,
        rating: found.rating,
        review_count: found.review_count,
      }
    : null

  const phones = contacts.map((c) => c.phone_e164).filter((p): p is string => Boolean(p))
  const suppressed = new Set<string>()
  if (phones.length) {
    // Callers and admins can read Do not contact; viewers cannot and simply see no strike-through.
    const { data } = await sb.from('suppression').select('phone_e164').in('phone_e164', phones)
    for (const s of data ?? []) if (s.phone_e164) suppressed.add(s.phone_e164)
  }

  return {
    lead: {
      ...row,
      id: row.id,
      business_id: businessId,
      name: row.name ?? 'Unnamed business',
      stage: row.stage ?? 'new',
      // Only meaningful while the stage is Lost or Not now (lib/outcomes).
      lost_reason: evidence.data?.business_id === businessId ? evidence.data.lost_reason : null,
    },
    business,
    contacts,
    suppressedPhones: [...suppressed],
    signals,
    facts,
    score: found?.scores[0] ?? null,
    activities: activities.data ?? [],
    feedback: feedback.data ?? [],
    pages,
  }
}

/** Deal value, monthly retainer and currency for one lead. Admins only: the admin view returns nothing for anyone else. */
export async function getLeadMoney(leadId: string) {
  const money = await getMoney(await createClient(), [leadId])
  return money.get(leadId) ?? null
}

export type LeadDetail = NonNullable<Awaited<ReturnType<typeof getLeadDetail>>>

/** Proposal files for a lead (private bucket; links are signed for 60 seconds when opened). */
export async function getProposals(leadId: string) {
  const sb = await createClient()
  const { data, error } = await sb.storage.from('proposals').list(leadId, { limit: 50, sortBy: { column: 'created_at', order: 'desc' } })
  if (error) return []
  return (data ?? [])
    .filter((f) => f.name && !f.name.startsWith('.'))
    .map((f) => ({
      path: `${leadId}/${f.name}`,
      name: f.name.replace(/^\d+-/, ''),
      size: Number((f.metadata as { size?: number } | null)?.size ?? 0),
      createdAt: f.created_at ?? null,
    }))
}
