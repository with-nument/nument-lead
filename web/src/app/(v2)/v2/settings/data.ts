import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { OUTREACH_KEYS, toMailbox, toSendingSettings, type Mailbox, type SendingSettings } from './sending'

// The tables of migration 0022 are not in database.types yet (lane W3 regenerates it), so they are read through
// a loosely typed handle here, and every row is checked by toMailbox before use.
type Loose = { from: (table: string) => { select: (cols: string) => LooseQuery } }
type LooseQuery = PromiseLike<{ data: unknown[] | null; error: { code?: string } | null }> & {
  eq: (col: string, v: unknown) => LooseQuery
  not: (col: string, op: string, v: unknown) => LooseQuery
  order: (col: string, opts: { ascending: boolean }) => LooseQuery
  limit: (n: number) => LooseQuery
}

/** How many of the last sends the health line looks at (the engine's guard uses a window like it). */
export const BOUNCE_WINDOW = 100

export type SendingData = { settings: SendingSettings; mailboxes: Mailbox[]; bounces: { bounced: number; sent: number } }

/**
 * Mailbox, sending settings and the bounce share of the last sends. Admin only: runs as the user, so Row Level
 * Security returns nothing to anyone else, and the page can start it while the role is checked.
 */
export async function getSendingData(): Promise<SendingData> {
  const sb = await createClient()
  const loose = sb as unknown as Loose
  const [settings, boxes, sends] = await Promise.all([
    sb.from('settings').select('key, value').in('key', [...OUTREACH_KEYS]),
    loose.from('mailboxes').select('id, email, display_name, status, paused_reason, warmup_started_on, sent_today, sent_day, last_error, connected_at').order('email', { ascending: true }),
    loose
      .from('email_messages')
      .select('status, error')
      .eq('direction', 'out')
      .not('sent_at', 'is', null)
      .order('sent_at', { ascending: false })
      .limit(BOUNCE_WINDOW),
  ])
  if (settings.error) throw settings.error
  // A project without migration 0022 has no mailbox yet: show "not connected" rather than an error.
  const rows = boxes.error ? [] : (boxes.data ?? [])
  const sent = sends.error ? [] : ((sends.data ?? []) as { error?: string | null }[])
  return {
    settings: toSendingSettings(settings.data ?? []),
    mailboxes: rows.map(toMailbox).filter((m): m is Mailbox => m !== null),
    bounces: { bounced: sent.filter((m) => m.error === 'bounced').length, sent: sent.length },
  }
}
