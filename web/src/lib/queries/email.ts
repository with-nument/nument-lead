import 'server-only'
import { createClient } from '@/lib/supabase/server'
import {
  toCallsPage,
  toInboxPage,
  toLeadConversation,
  type CallsPage,
  type InboxCursor,
  type InboxPage,
  type InboxSummary,
  type InboxTab,
  type LeadConversation,
} from './email-data'

export type * from './email-data'

export const INBOX_PAGE_SIZE = 50

/**
 * One page of the Inbox and the count of every tab, in one database call (inbox_page, migration 0033). Runs as
 * the user under Row Level Security: admins and callers see the email, viewers get empty tabs.
 */
export async function getInboxPage(tab: InboxTab, cursor: InboxCursor | null = null, pageSize = INBOX_PAGE_SIZE): Promise<InboxPage> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('inbox_page', {
    tab,
    page_size: pageSize,
    ...(cursor ? { cursor_at: cursor.at, cursor_id: cursor.id } : {}),
  })
  if (error) throw error
  return toInboxPage(data)
}

/** For Today: how many replies and drafts wait, and the newest few replies (with their drafted answers). */
export async function getInboxSummary(replies = 3): Promise<InboxSummary> {
  const page = await getInboxPage('replies', null, replies)
  return { counts: page.counts, replies: page.items }
}

/** Every booked call: today, coming up and the last 30 days, with brief, offer, plan views and proposal (calls_page). */
export async function getCallsPage(): Promise<CallsPage> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('calls_page')
  if (error) throw error
  return toCallsPage(data)
}

/** A lead's emails, offers, plan page views, startup profile, briefs and proposals; null when not visible (lead_conversation). */
export async function getLeadConversation(leadId: string): Promise<LeadConversation | null> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('lead_conversation', { lead_id: leadId })
  if (error) throw error
  return toLeadConversation(data)
}
