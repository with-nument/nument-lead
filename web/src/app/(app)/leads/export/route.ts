import { getSessionUser } from '@/lib/auth'
import { toCsv } from '@/lib/csv'
import { istDate } from '@/lib/dates'
import { parseLeadFilters } from '@/lib/leads-filters'
import { getLeadsForExport } from '@/lib/queries/leads'
import { getTeam } from '@/lib/queries/shared'
import { pitchLabel, signalLabel } from '@/lib/signals'
import { stageOf } from '@/lib/stages'

const BASE_COLUMNS = [
  { key: 'name', label: 'Company' },
  { key: 'grade', label: 'Grade' },
  { key: 'total', label: 'Score' },
  { key: 'stage', label: 'Stage' },
  { key: 'segment_id', label: 'Segment' },
  { key: 'city', label: 'City' },
  { key: 'country', label: 'Country' },
  { key: 'website', label: 'Website' },
  { key: 'category', label: 'Category' },
  { key: 'contact_name', label: 'Contact' },
  { key: 'contact_role', label: 'Role' },
  { key: 'phone_e164', label: 'Phone' },
  { key: 'phone_type', label: 'Phone type' },
  { key: 'phone_source', label: 'Phone source' },
  { key: 'email', label: 'Email' },
  { key: 'top_signal', label: 'Top signal' },
  { key: 'top_signal_quote', label: 'Signal quote' },
  { key: 'top_signal_url', label: 'Signal link' },
  { key: 'top_signal_at', label: 'Signal date' },
  { key: 'pitch', label: 'Pitch mode' },
  { key: 'angle', label: 'Angle' },
  { key: 'owner', label: 'Owner' },
  { key: 'next_step', label: 'Next step' },
  { key: 'due_at', label: 'Due' },
  { key: 'wa_at', label: 'First message' },
  { key: 'message', label: 'Message' },
  { key: 'created_at', label: 'Added' },
  { key: 'id', label: 'Lead id' },
]

/**
 * CSV of the current Leads view (or the selected rows). Admins get a Deal value column; callers never
 * do, because their rows come from v_leads_caller, which has no money column (plan 15.6.4).
 */
export async function GET(request: Request) {
  const user = await getSessionUser()
  if (!user || user.role === 'viewer') return new Response('Not allowed', { status: 403 })
  const params = new URL(request.url).searchParams
  const filters = parseLeadFilters(params)
  const ids = params.getAll('ids').filter((id) => /^[0-9a-f-]{36}$/i.test(id))
  const isAdmin = user.role === 'admin'
  const [rows, team] = await Promise.all([
    getLeadsForExport(filters, { userId: user.id, today: istDate(), withMoney: isAdmin }, ids),
    getTeam(),
  ])
  const owners = new Map(team.map((m) => [m.id, m.name]))
  const out = rows.map((r) => ({
    ...r,
    stage: stageOf(r.stage).label,
    top_signal: r.top_signal_type ? signalLabel(r.top_signal_type) : '',
    pitch: pitchLabel(r.pitch_mode),
    owner: r.owner_id ? (owners.get(r.owner_id) ?? '') : '',
  }))
  const columns = isAdmin ? [...BASE_COLUMNS, { key: 'deal_value_inr', label: 'Deal value (INR)' }] : BASE_COLUMNS
  const csv = toCsv(out, columns)
  return new Response(csv, {
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="nument-leads-${istDate()}.csv"`,
      'Cache-Control': 'no-store',
    },
  })
}
