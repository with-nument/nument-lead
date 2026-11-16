// What each Today section shows. The page builds these from home_summary today; the email work (lane W3) feeds
// replies, calls and proposals from its own tables later, through the same shapes. Plain data only, so a server
// page can pass them to the client sections.

/** What a person can approve, send or mark. Every change is optimistic with a 30 second inline Undo. */
export type TodayActionResult = { ok: true; message?: string } | { ok: false; message: string }

/** A founder's reply with the answer we drafted for it, waiting for approval. */
export type ReplyItem = {
  id: string
  leadId: string
  /** The person who wrote. */
  person: string
  company: string
  /** Their words, short. */
  quote: string
  /** What the drafted answer does, in one plain line ("Suggests two call slots and a ₹2–3L range"). */
  suggestion: string | null
}

/** A call booked for today. */
export type CallItem = {
  id: string
  leadId: string
  /** Display time in India time, such as "6:30 pm". */
  time: string
  person: string
  company: string
  /** One line about the call ("Brief ready · wants a contract review assistant"). */
  note: string | null
  /** Where the call brief opens. Defaults to the lead page. */
  href?: string
}

/** A proposal drafted from a call, waiting to be reviewed and sent. */
export type ProposalItem = {
  id: string
  leadId: string
  company: string
  person: string | null
  /** "Drafted from Friday's call · kitchen ops app, 6 weeks · ₹2.4L" */
  note: string | null
  href?: string
}

/** A follow-up due today or earlier. */
export type FollowupItem = {
  leadId: string
  company: string
  person: string | null
  which: 'd3' | 'd7'
  /** "Day 3 follow-up · due today" */
  note: string
  overdue: boolean
}

/** A new startup ready to contact (the send list). */
export type StartupItem = {
  leadId: string
  company: string
  grade: string | null
  city: string | null
  person: string | null
  /** Why now: the strongest signal, in plain words. */
  signal: string | null
}

/** The numbers card at the side. */
export type OvernightStat = { label: string; value: string }
export type OvernightHealth = { tone: 'ok' | 'warn' | 'bad'; text: string }

/** Which section holds the one solid button on the page (the first one with something to do). */
export type TodayStep = 'replies' | 'calls' | 'proposals' | 'followups' | 'startups'
