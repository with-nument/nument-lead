// What the v2 lead page shows beyond lead_detail, filled from lead_conversation (migration 0033) by extras.ts.
// Without an email thread the Conversation segment shows the lead's own message and follow-ups. Plain data
// only, so a server page can pass it.
import type { ActionResult } from '@/lib/action-result'

export type ConversationMessageStatus =
  | 'draft'
  | 'review'
  | 'approved'
  | 'queued'
  | 'sending'
  | 'sent'
  | 'failed'
  | 'cancelled'
  | 'received'

/** One email in the thread (email_messages). */
export type ConversationMessage = {
  id: string
  direction: 'out' | 'in'
  /** The sequence step for outgoing emails (0 = first email, then day 3, 7, 12); null for replies. */
  step: number | null
  subject: string | null
  body: string | null
  status: ConversationMessageStatus
  /** sent_at for sent mail, created_at for received mail, scheduled_for for queued mail. */
  at: string | null
  /** Who wrote it, for received mail ("Maya Rao"). */
  from?: string | null
}

/** The email thread with this lead (email_threads), oldest message first. */
export type ConversationThread = {
  id: string
  toEmail: string
  status: 'open' | 'stopped' | 'done'
  stopReason: string | null
  pausedUntil: string | null
  messages: ConversationMessage[]
  /** A reply drafted for the founder to approve (email_messages.suggested_reply), if one is waiting. */
  suggestedReply: { messageId: string; body: string } | null
}

/** Approve (and queue) the suggested reply, with the founder's edits. A server action. */
export type ApproveReplyAction = (input: { leadId: string; messageId: string; body: string }) => Promise<ActionResult>

/** Puts an approved reply back in review (the Undo of Approve). A server action. */
export type ReopenReplyAction = (input: { leadId: string; messageId: string }) => Promise<ActionResult>

/** Props of the Conversation segment. Export for lane W3. */
export type ConversationProps = {
  leadId: string
  thread: ConversationThread | null
  approveReply?: ApproveReplyAction
}

/** The lead's plan page (plan_pages): views and clicks, never email opens. */
export type PlanPageSummary = { views: number; lastViewedAt: string | null; url: string | null; note?: string | null }

/** The best offer for this lead (lead_offers rank 1 joined to offers). */
export type BestOffer = { name: string; text: string; timeline?: string | null; range?: string | null; why?: string | null }

/** One known answer of the startup profile (0028), with the plain reason and up to two sources. */
export type ProfileRow = { key: string; label: string; value: string; why: string | null; sources: { url: string; host: string; date: string }[] }

/** Where the email sequence with the founder stands ("Replied 16 Nov", "Stopped: bounced"). */
export type EmailStatus = { tone: 'ok' | 'warn' | 'bad' | 'muted'; text: string }

/** Everything optional the page can be given on top of lead_detail. */
export type LeadExtras = {
  thread?: ConversationThread | null
  approveReply?: ApproveReplyAction
  reopenReply?: ReopenReplyAction
  planPage?: PlanPageSummary | null
  offer?: BestOffer | null
  /** The startup profile's known answers with their evidence (Why). */
  profile?: ProfileRow[]
  /** The email sequence's state (inspector). */
  emailStatus?: EmailStatus | null
  /** What happens next on the email side (inspector, under Next step). */
  nextEmail?: string | null
}
