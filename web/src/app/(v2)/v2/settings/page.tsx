import type { Metadata } from 'next'
import { Suspense } from 'react'
import { Mail } from 'lucide-react'
import { Column, Columns, Meter, Panel, Row, Section, StatusDot } from '@/app/(v2)/v2/_parts/section'
import { Button } from '@/components/ui2/button'
import { Page } from '@/components/ui2/large-title'
import { Skeleton } from '@/components/ui2/skeleton'
import { early, requireRole, requireUser } from '@/lib/auth'
import { formatDate, istDate, relativeAge } from '@/lib/dates'
import { formatPhone } from '@/lib/phone'
import { getRecipients, getSuppression, getUsers } from '@/lib/queries/settings'
import { getTeam } from '@/lib/queries/shared'
import { ROLE_HINT, ROLE_LABEL } from '@/lib/roles'
import { SUPPRESSION_REASON_LABEL } from '@/lib/suppression'
import { getSendingData, type SendingData } from './data'
import { DesignSwitch } from './_parts/design'
import { PauseSwitch } from './_parts/pause'
import { PasswordForm, ProfilePanel } from './_parts/profile'
import { AddRecipientButton, RecipientsPanel } from './_parts/recipients'
import { SuppressionPanel, type SuppressionView } from './_parts/suppression'
import { InviteButton, TeamPanel, type TeamUser } from './_parts/team'
import { MAILBOX_STATUS_LABEL, MAILBOX_STATUS_TONE, MODE_LABEL, mailboxHealth, warmupState } from './sending'
import { suppressionCounts } from './summary'

export const metadata: Metadata = { title: 'Settings' }

const SUBTITLE = 'Your account, your team and how email goes out.'

export default function SettingsPage({ searchParams }: PageProps<'/v2/settings'>) {
  return (
    <Page title="Settings" subtitle={SUBTITLE}>
      <Suspense fallback={<SettingsSkeleton />}>
        <Settings searchParams={searchParams} />
      </Suspense>
    </Page>
  )
}

async function Settings({ searchParams }: Pick<PageProps<'/v2/settings'>, 'searchParams'>) {
  const [user, sp] = await Promise.all([requireUser(), searchParams])
  const forced = user.mustChangePassword || sp.change_password === '1'
  const isAdmin = user.role === 'admin'
  // Admin reads run as the user (Row Level Security: admins only) and start before the stricter role check.
  const admin = isAdmin && !forced ? { sending: early(getSendingData()), recipients: early(getRecipients()), suppression: early(getSuppression()) } : null

  if (forced) {
    // The first sign in with a temporary password: nothing else until it is changed.
    return (
      <div className="max-w-[560px]">
        <Section id="password-title" title="Choose your own password to continue" description="You signed in with a temporary password. The rest of the app opens right after.">
          <Panel>
            <div className="p-4 lg:p-5">
              <PasswordForm forced />
            </div>
          </Panel>
        </Section>
      </div>
    )
  }

  const profile = (
    <Section id="profile-title" title="Profile">
      <ProfilePanel name={user.name} email={user.email} roleLabel={ROLE_LABEL[user.role]} roleHint={ROLE_HINT[user.role]} />
    </Section>
  )
  const design = (
    <Section id="design-title" title="Design" description="Pages not redesigned yet open in the classic design.">
      <Panel>
        <Row trailing={<DesignSwitch />}>New design</Row>
      </Panel>
    </Section>
  )

  if (!admin) {
    return (
      <div className="flex max-w-[560px] flex-col gap-7">
        {profile}
        {design}
      </div>
    )
  }

  // Users come from the service role: check the role with the Auth server first.
  const me = await requireRole(['admin'], { verified: true })
  const [users, sending, recipients, suppression, team] = await Promise.all([getUsers(), admin.sending, admin.recipients, admin.suppression, getTeam()])
  const now = new Date()
  const teamUsers: TeamUser[] = users.map((u) => ({
    id: u.id,
    name: u.name,
    email: u.email,
    role: u.role,
    lastSignIn: u.lastSignInAt ? relativeAge(u.lastSignInAt, now) : '',
    disabled: u.disabled,
    mustChangePassword: u.mustChangePassword,
    isMe: u.id === me.id,
  }))
  // You first, then everyone else by name.
  teamUsers.sort((a, b) => Number(b.isMe) - Number(a.isMe))
  const names = new Map(team.map((m) => [m.id, m.name]))
  const entries: SuppressionView[] = suppression.map((r) => ({
    ...r,
    label: r.phone_e164 ? formatPhone(r.phone_e164) : (r.email ?? r.web_domain ?? ''),
    reasonLabel: SUPPRESSION_REASON_LABEL[r.reason] ?? r.reason,
    added: formatDate(r.added_at, now),
    by: r.added_by ? (names.get(r.added_by) ?? 'A teammate') : 'The engine',
  }))

  return (
    <Columns>
      <Column>
        {profile}
        <Section id="team-title" title="Team" description="People who can use Lead desk." action={<InviteButton />}>
          <TeamPanel users={teamUsers} />
        </Section>
        <MailboxSection data={sending} />
        {design}
      </Column>
      <Column>
        <SendingSection data={sending} today={istDate(now)} />
        <Section id="email-title" title="Email recipients" description="Who gets the morning list, alerts and the weekly report." action={<AddRecipientButton />}>
          <RecipientsPanel recipients={recipients} />
        </Section>
        <Section id="dnc-title" title="Do not contact" description="We never email or call these people or companies.">
          <SuppressionPanel entries={entries} summary={suppressionCounts(suppression)} />
        </Section>
      </Column>
    </Columns>
  )
}

function MailboxSection({ data }: { data: SendingData }) {
  return (
    <Section id="mailbox-title" title="Mailbox" description="Emails go out from here, and replies land in Inbox.">
      <Panel>
        {data.mailboxes.map((m) => (
          <Row key={m.id} trailing={<StatusDot tone={MAILBOX_STATUS_TONE[m.status]}>{MAILBOX_STATUS_LABEL[m.status]}</StatusDot>}>
            <div className="flex min-w-0 items-center gap-3.5">
              <Mail aria-hidden className="size-4 shrink-0 text-label-2" />
              <div className="min-w-0">
                <p className="truncate font-medium">{m.email}</p>
                <p className="type-caption truncate text-label-3">
                  {m.status === 'error' && m.last_error ? m.last_error : `Gmail · sends as ${m.display_name}`}
                </p>
              </div>
            </div>
          </Row>
        ))}
        <Row
          trailing={
            <Button size="small" disabled aria-describedby="connect-gmail-note">
              Connect Gmail
            </Button>
          }
        >
          <p className="text-label-3">{data.mailboxes.length ? 'Add another mailbox to send more each day' : 'No mailbox connected yet'}</p>
          <p id="connect-gmail-note" className="type-caption text-label-3">
            Coming soon
          </p>
        </Row>
      </Panel>
    </Section>
  )
}

function SendingSection({ data, today }: { data: SendingData; today: string }) {
  const box = data.mailboxes.find((m) => m.status !== 'disconnected') ?? null
  const w = box ? warmupState(box, data.settings.warmup, today) : null
  const health = mailboxHealth(box, data.bounces, data.settings.paused)
  return (
    <Section id="sending-title" title="Sending" description="New mailboxes start slow so emails reach the inbox, not spam.">
      <Panel>
        {w ? (
          <div className="px-4 py-4 lg:px-5 lg:py-[18px]">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[15px] lg:text-[14.5px]">
              <span className="font-medium text-label-1">
                {w.done ? 'Warm-up done' : !w.started ? 'Warm-up starts with the first email' : `Warm-up · week ${w.week} of ${w.weeks}`}
              </span>
              <span className="tabular-nums text-label-3">{w.done ? `${w.capEnd} a day` : `${w.capNow} a day now · ${w.capEnd} at the end`}</span>
            </div>
            <Meter className="mt-2.5" label="Warm-up" value={w.done ? w.weeks : w.started ? w.week : 0} max={w.weeks} />
          </div>
        ) : null}
        <Row label="Sent today">
          <span className="tabular-nums">{w ? `${w.sentToday} of ${w.capNow}` : 'None'}</span>
        </Row>
        <Row label="Autopilot">{MODE_LABEL[data.settings.mode]}</Row>
        <Row label="Health">
          <StatusDot tone={health.tone}>{health.label}</StatusDot>
        </Row>
        <Row label="Pause all sending" trailing={<PauseSwitch paused={data.settings.paused} />}>
          <span className="block text-label-3">{data.settings.paused ? 'Paused: nothing goes out' : ''}</span>
        </Row>
      </Panel>
    </Section>
  )
}

/** Matches the two columns of panels, so nothing jumps when they arrive. */
function SettingsSkeleton() {
  const block = (rows: number) => (
    <div className="flex flex-col">
      <Skeleton className="mb-3 ml-1 h-4 w-24" />
      <div role="presentation" className="material-panel overflow-hidden rounded-[20px] [&>*+*]:hairline-t">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex min-h-14 items-center gap-4 px-4 lg:px-5">
            <Skeleton className="h-3.5 w-20" />
            <Skeleton className="h-3.5 w-2/5" />
          </div>
        ))}
      </div>
    </div>
  )
  return (
    <div role="status" aria-label="Loading settings" className="grid items-start gap-7 lg:grid-cols-2">
      <div className="flex flex-col gap-7">
        {block(5)}
        {block(2)}
      </div>
      <div className="flex flex-col gap-7">
        {block(5)}
        {block(3)}
      </div>
    </div>
  )
}
