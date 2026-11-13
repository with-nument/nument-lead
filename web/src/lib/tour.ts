// The first-visit product tour: its steps and the pure logic around them (who sees which step,
// when it starts, where a step goes, where the card sits). The component lives in
// components/tour; this file has no DOM access so it can be unit tested.
import type { Role } from '@/lib/roles'

/** Key in the user's own user_metadata. Harmless if a user edits it: it only hides the tour. */
export const TOUR_META_KEY = 'tour_completed_at'
/** localStorage mirror, per user, so a finished tour never flashes back before the server answers. */
export const tourStorageKey = (userId: string) => `nument:tour-done:${userId}`
/** Stands for "a lead page": the tour opens the first lead it can find, or explains it without one. */
export const LEAD_ROUTE = ':lead'

type Copy = { title: string; body: string; fallback?: string }

export type TourStep = Copy & {
  id: string
  /** Page the step belongs to. Omitted: stays on the current page. */
  route?: string
  /** data-tour names to highlight, the first visible one wins. Omitted or none found: a centred card. */
  target?: readonly string[]
  /** Who sees the step. Omitted: everyone. */
  roles?: readonly Role[]
  /** Different words for a role (an admin sees more than a caller). */
  forRole?: Partial<Record<Role, Partial<Copy>>>
}

const ADMIN = ['admin'] as const
const SENDERS = ['admin', 'caller'] as const

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to Nument Leads',
    body: 'Quick tour, about a minute. Every morning the engine finds businesses that could use us, checks the proof and writes the first WhatsApp message. You send it, follow up and close. Skip whenever you like.',
  },
  {
    id: 'today-numbers',
    route: '/',
    target: ['today-kpis'],
    title: 'Your day at a glance',
    body: "Today opens with the numbers that matter: leads ready to send, messages sent this week, who's talking, proposals out and anything overdue.",
    forRole: {
      admin: {
        body: "Today opens with the numbers that matter: leads ready to send, messages sent this week, who's talking, proposals out, anything overdue and what we won this month.",
      },
    },
  },
  {
    id: 'today-send-list',
    route: '/',
    target: ['send-list'],
    title: 'The send list',
    body: "New A and B leads, best first. Each one shows why it's here and the message, ready to go. The engine adds fresh ones every morning by 7:30 am.",
  },
  {
    id: 'today-whatsapp',
    route: '/',
    roles: SENDERS,
    target: ['send-actions'],
    title: 'One tap to send',
    body: 'WhatsApp Web on a laptop, the WhatsApp app on a phone. The message opens already typed, and the same tap marks the lead Contacted. Slipped? Hit Undo.',
    fallback:
      'Every lead here gets two buttons: WhatsApp Web for your laptop and the WhatsApp app for your phone. The message opens already typed, and the same tap marks the lead Contacted. Slipped? Hit Undo.',
  },
  {
    id: 'today-followups',
    route: '/',
    target: ['followups'],
    title: 'Follow-ups due',
    body: "Day 3 and day 7 nudges for people who haven't replied yet. They turn up here on the right day, so nobody slips through.",
  },
  {
    id: 'leads-filters',
    route: '/leads',
    target: ['lead-filters', 'lead-filters-mobile'],
    title: 'Leads: the full list',
    body: 'Every lead the engine has found. Narrow it down by stage, grade, segment, city, signal and more. Your filters live in the link, so you can share exactly what you see.',
  },
  {
    id: 'leads-views',
    route: '/leads',
    target: ['save-view'],
    title: 'Saved views',
    body: 'Use the same filters every day? Save them as a view and open them in one click. Keep it for yourself or share it with the team.',
  },
  {
    id: 'leads-grades',
    route: '/leads',
    target: ['grade-filter', 'lead-row'],
    title: 'Grades A to D',
    body: 'Each lead is scored out of 100: need (35), ability to pay (35), fit (10) and how directly we can reach them (20). A is 75 and up, B is 55 and up, and those two land in your send list. C and D wait here for later.',
  },
  {
    id: 'lead-why',
    route: LEAD_ROUTE,
    target: ['lead-why'],
    title: 'Why this lead',
    body: 'Every lead comes with proof: the score, the reasons behind it and the signals, each with the exact quote and a link to where we found it. Give it a skim before you send.',
    fallback:
      "Open any lead and you'll see why it's here: the score, the reasons behind it and the signals, each with the exact quote and a link to where we found it.",
  },
  {
    id: 'lead-message',
    route: LEAD_ROUTE,
    target: ['lead-message'],
    title: 'The message',
    body: 'The first message, ready to tweak. Not feeling it? Swap in the alternate. The day 3 and day 7 follow-ups sit right below. Save stays locked until the message passes our checks.',
    fallback:
      "Each lead has a first message you can tweak, an alternate if it doesn't feel right, and day 3 and day 7 follow-ups. Save stays locked until the message passes our checks.",
    forRole: {
      viewer: {
        body: 'The first message, an alternate and the day 3 and day 7 follow-ups, exactly as the team will send them.',
        fallback: 'Each lead has a first message, an alternate and day 3 and day 7 follow-ups, exactly as the team will send them.',
      },
    },
  },
  {
    id: 'lead-stage',
    route: LEAD_ROUTE,
    target: ['lead-controls'],
    title: 'Stage and next step',
    body: 'Move the lead along and set the next step with a due date. Sending from Today updates this for you.',
    fallback: 'On every lead you move the stage along and set the next step with a due date. Sending from Today updates this for you.',
    forRole: {
      admin: {
        title: 'Stage, owner and next step',
        body: 'Move the lead along, pick who owns it and set the next step with a due date. Sending from Today updates this for you.',
        fallback: 'On every lead you move the stage along, pick who owns it and set the next step with a due date. Sending from Today updates this for you.',
      },
      viewer: {
        body: 'Where the lead stands and what happens next, with a due date.',
        fallback: 'Every lead shows where it stands and what happens next, with a due date.',
      },
    },
  },
  {
    id: 'lead-notes',
    route: LEAD_ROUTE,
    target: ['lead-notes'],
    title: 'Notes',
    body: 'Anything you learn on a call goes here, so the whole team knows. The newest note also shows in the Google Sheet.',
    fallback: 'Every lead has a notes box. Anything you learn on a call goes there, so the whole team knows. The newest note also shows in the Google Sheet.',
  },
  {
    id: 'lead-timeline',
    route: LEAD_ROUTE,
    target: ['lead-timeline'],
    title: 'Timeline',
    body: 'Everything that happened to the lead: who did what and when, from the app, the sheet and the engine, with sources.',
    fallback: 'Every lead keeps a timeline: who did what and when, from the app, the sheet and the engine, with sources.',
  },
  {
    id: 'lead-deal',
    route: LEAD_ROUTE,
    roles: ADMIN,
    target: ['lead-deal'],
    title: 'Deal card',
    body: 'Deal value and proposal files live here. Only admins see this card. Callers never see money anywhere in the app.',
    fallback: 'On every lead, admins get a deal card for the deal value and proposal files. Callers never see money anywhere in the app.',
  },
  {
    id: 'pipeline',
    route: '/pipeline',
    target: ['pipeline-board'],
    title: 'Pipeline',
    body: 'Every lead after the first message, one column per stage. Drag a card to move it. On a phone, press and hold first. The keyboard works too: space to pick up, arrows to move.',
    forRole: { viewer: { body: 'Every lead after the first message, one column per stage, so you can see where things stand.' } },
  },
  {
    id: 'insights',
    route: '/insights',
    target: ['insights'],
    title: 'Insights',
    body: "What's working: replies by segment, country, signal and message angle, plus how good the leads have been. It fills up as you send.",
    forRole: {
      admin: {
        body: "What's working: replies by segment, country, signal and message angle, plus how good the leads have been and what they cost. It fills up as you send.",
      },
    },
  },
  {
    id: 'engine-budget',
    route: '/engine',
    roles: ADMIN,
    target: ['engine-budget'],
    title: 'Engine: the budget',
    body: 'What the engine spent today against the daily cap, ₹750 unless you change it here. It stops spending when it reaches the cap.',
  },
  {
    id: 'engine-sources',
    route: '/engine',
    roles: ADMIN,
    target: ['engine-sources'],
    title: 'Sources and runs',
    body: 'Switch off any source in one click if it acts up. Below it are the recent runs, and Run now at the top starts one by hand.',
  },
  {
    id: 'inbox',
    route: '/inbox',
    roles: ADMIN,
    target: ['inbox-paste'],
    title: 'Inbox',
    body: 'Spot someone on LinkedIn or X asking for help? Copy the post and paste it here. The engine works from your text and never opens those sites.',
  },
  {
    id: 'settings',
    route: '/settings',
    target: ['settings-password'],
    title: 'Settings',
    body: 'Change your name and password, or sign out on other devices.',
  },
  {
    id: 'users',
    route: '/settings/users',
    roles: ADMIN,
    target: ['settings-users'],
    title: 'Users and roles',
    body: 'Add teammates as admin, caller or viewer. They get a temporary password once and pick their own on first sign in. Resets and switching someone off happen here too.',
  },
  {
    id: 'do-not-contact',
    route: '/settings/suppression',
    roles: ADMIN,
    target: ['settings-dnc'],
    title: 'Do not contact',
    body: "Numbers on this list never get a message. The engine skips them and the app won't offer them again. Marking a lead as Wrong contact adds the number here too.",
  },
  {
    id: 'email-recipients',
    route: '/settings/email',
    roles: ADMIN,
    target: ['settings-email'],
    title: 'Email recipients',
    body: 'Who gets the morning list, alerts and the weekly report by email. Add teammates, switch each email on or off per person, and send a test. Only admins see spend in them.',
  },
  {
    id: 'done',
    route: '/',
    target: ['tour-button'],
    title: "That's the tour",
    body: 'Replay it any time from this button or your account menu. Now go send some messages.',
  },
]

export type ResolvedStep = Omit<TourStep, 'forRole' | 'roles'>

/** The steps a role gets, with that role's words. Pages a role cannot open are left out. */
export function tourStepsFor(role: Role, steps: readonly TourStep[] = TOUR_STEPS): ResolvedStep[] {
  return steps
    .filter((s) => !s.roles || s.roles.includes(role))
    .map((s) => {
      const { forRole, roles, ...rest } = s
      void roles
      return { ...rest, ...forRole?.[role] }
    })
}

/** What the card says: the fallback when the highlighted part is not on the page (for example no leads yet). */
export const stepText = (step: Pick<TourStep, 'body' | 'fallback'>, hasTarget: boolean) => (hasTarget ? step.body : (step.fallback ?? step.body))

/** The completion time from user_metadata, only if it is a real date. Anything else counts as not done. */
export function completedAtOf(userMetadata: unknown): string | null {
  if (!userMetadata || typeof userMetadata !== 'object') return null
  const v = (userMetadata as Record<string, unknown>)[TOUR_META_KEY]
  return typeof v === 'string' && !Number.isNaN(Date.parse(v)) ? v : null
}

/** Starts by itself only once: after the forced password change, and never after it was finished or skipped. */
export function shouldAutoStart(s: { mustChangePassword: boolean; completedAt: string | null; doneLocally: boolean }) {
  return !s.mustChangePassword && !s.completedAt && !s.doneLocally
}

const LEAD_PATH = /^\/leads\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export const isLeadPath = (path: string) => LEAD_PATH.test(path)

/** The lead page to show: the one already open, else the first lead link on the page, else none. */
export function pickLeadPath(currentPath: string, hrefs: readonly string[]): string | null {
  if (isLeadPath(currentPath)) return currentPath
  for (const href of hrefs) {
    const path = href.split(/[?#]/)[0] ?? ''
    if (isLeadPath(path)) return path
  }
  return null
}

/** Where a step lives. Null means stay put (no route, or a lead step when there are no leads). */
export function routeOf(step: Pick<TourStep, 'route'>, leadPath: string | null): string | null {
  if (!step.route) return null
  return step.route === LEAD_ROUTE ? leadPath : step.route
}

export const needsNavigation = (pathname: string, route: string | null) => route !== null && pathname !== route

export type Rect = { top: number; left: number; width: number; height: number }
export type Size = { width: number; height: number }
export type Placement = { top: number; left: number; width: number; side: 'center' | 'bottom' | 'top' | 'right' | 'left' | 'dock-top' | 'dock-bottom' }

export const PHONE_MAX = 640
export const CARD_WIDTH = 360
const MARGIN = 16
const GAP = 14

const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), Math.max(min, max))

/**
 * Where the card goes. No target: centred. Phones: docked to the top or bottom edge, away from
 * the highlight. Wider screens: below, above, right or left of the highlight, the first that fits,
 * kept inside the window; if none fits, docked at the bottom.
 */
export function placeCard(target: Rect | null, card: Size, view: Size): Placement {
  const phone = view.width < PHONE_MAX
  const width = phone ? view.width - MARGIN * 2 : Math.min(CARD_WIDTH, view.width - MARGIN * 2)
  if (!target) {
    return { side: 'center', width, left: Math.round((view.width - width) / 2), top: Math.round(clamp((view.height - card.height) / 2, MARGIN, view.height - card.height - MARGIN)) }
  }
  if (phone) {
    const middle = target.top + target.height / 2
    // Card at the bottom unless the highlight sits in the lower half and there is room above it.
    const roomAbove = target.top - MARGIN
    const dockTop = middle > view.height / 2 && roomAbove >= card.height + GAP
    return dockTop
      ? { side: 'dock-top', width, left: MARGIN, top: MARGIN }
      : { side: 'dock-bottom', width, left: MARGIN, top: Math.max(MARGIN, view.height - card.height - MARGIN) }
  }
  const alignX = clamp(target.left, MARGIN, view.width - width - MARGIN)
  const alignY = clamp(target.top, MARGIN, view.height - card.height - MARGIN)
  const below = target.top + target.height + GAP
  if (below + card.height <= view.height - MARGIN) return { side: 'bottom', width, left: alignX, top: below }
  const above = target.top - GAP - card.height
  if (above >= MARGIN) return { side: 'top', width, left: alignX, top: above }
  const right = target.left + target.width + GAP
  if (right + width <= view.width - MARGIN) return { side: 'right', width, left: right, top: alignY }
  const left = target.left - GAP - width
  if (left >= MARGIN) return { side: 'left', width, left, top: alignY }
  return { side: 'dock-bottom', width, left: view.width - width - MARGIN, top: Math.max(MARGIN, view.height - card.height - MARGIN) }
}
