'use client'

import { useState } from 'react'
import { Check, Copy, Ellipsis, Plus } from 'lucide-react'
import { createUser, resetPasswordForUser, setDisabled, setRole, type CreatedUser } from '@/app/(app)/settings/users/actions'
import { Field, FormError, inputClass, Submit } from '@/app/(v2)/v2/_parts/form'
import { useFormAction, useRun } from '@/app/(v2)/v2/_parts/run'
import { Panel, Row } from '@/app/(v2)/v2/_parts/section'
import { Avatar } from '@/components/shell2/avatar'
import { IconButton } from '@/app/(v2)/v2/_parts/icon-button'
import { Button } from '@/components/ui2/button'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { Select } from '@/components/ui2/select'
import { Sheet, SheetContent } from '@/components/ui2/sheet'
import { initials } from '@/lib/format'
import { ROLE_HINT, ROLE_LABEL, ROLES, type Role } from '@/lib/roles'

export type TeamUser = {
  id: string
  name: string
  email: string
  role: Role | null
  /** "3 days ago", or empty when they never signed in. */
  lastSignIn: string
  disabled: boolean
  mustChangePassword: boolean
  isMe: boolean
}

type Secret = { email: string; tempPassword: string; title: string }

/** Settings > Team (admins): everyone who can sign in, their role, and a menu per person. */
export function TeamPanel({ users }: { users: TeamUser[] }) {
  const [secret, setSecret] = useState<Secret | null>(null)
  const [pending, run] = useRun()
  return (
    <>
      <Panel label="Team">
        {users.map((u) => (
          <Row
            key={u.id}
            className={u.disabled ? 'opacity-60' : undefined}
            trailing={
              <>
                <span className="type-subhead text-label-3 lg:text-[13px]">{u.disabled ? 'Disabled' : u.role ? ROLE_LABEL[u.role] : 'No role'}</span>
                <Menu>
                  <MenuTrigger asChild>
                    <IconButton aria-label={`Options for ${u.name}`} disabled={pending}>
                      <Ellipsis aria-hidden />
                    </IconButton>
                  </MenuTrigger>
                  <MenuContent>
                    <MenuLabel>Role</MenuLabel>
                    {ROLES.map((r) => (
                      <MenuItem key={r} disabled={u.role === r || (u.isMe && r !== 'admin')} onSelect={() => run(() => setRole({ userId: u.id, role: r }))}>
                        {u.role === r ? <Check aria-hidden /> : <span aria-hidden className="size-4 lg:size-4" />}
                        {ROLE_LABEL[r]}
                      </MenuItem>
                    ))}
                    <MenuSeparator />
                    <MenuItem
                      onSelect={() =>
                        run(() => resetPasswordForUser({ userId: u.id }), {
                          quiet: true,
                          onOk: (r) => r.data && setSecret({ email: u.email, tempPassword: r.data.tempPassword, title: 'New temporary password' }),
                        })
                      }
                    >
                      Reset password
                    </MenuItem>
                    {u.isMe ? null : (
                      <MenuItem destructive={!u.disabled} onSelect={() => run(() => setDisabled({ userId: u.id, disabled: !u.disabled }))}>
                        {u.disabled ? 'Enable account' : 'Disable account'}
                      </MenuItem>
                    )}
                  </MenuContent>
                </Menu>
              </>
            }
          >
            <div className="flex min-w-0 items-center gap-3">
              <Avatar initials={initials(u.name)} className="hairline-ring" />
              <div className="min-w-0">
                <p className="truncate">
                  <span className="font-medium">{u.isMe ? 'You' : u.name}</span>
                  <span className="text-label-3"> · {u.email}</span>
                </p>
                <p className="type-caption truncate text-label-3">
                  {u.mustChangePassword ? 'Has a temporary password' : u.lastSignIn ? `Last signed in ${u.lastSignIn}` : 'Never signed in'}
                </p>
              </div>
            </div>
          </Row>
        ))}
      </Panel>
      <SecretSheet secret={secret} onClose={() => setSecret(null)} />
    </>
  )
}

/** The Invite button and its sheet: a new account with a temporary password, shown once. */
export function InviteButton() {
  const [open, setOpen] = useState(false)
  const [secret, setSecret] = useState<Secret | null>(null)
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        <Plus aria-hidden />
        Invite
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Invite someone" description="They sign in with a temporary password and choose their own.">
          <InviteForm
            onCreated={(u) => {
              setOpen(false)
              setSecret({ ...u, title: 'Account created' })
            }}
          />
        </SheetContent>
      </Sheet>
      <SecretSheet secret={secret} onClose={() => setSecret(null)} />
    </>
  )
}

function InviteForm({ onCreated }: { onCreated: (u: CreatedUser) => void }) {
  const [role, setRoleValue] = useState<Role>('caller')
  const [state, action, pending] = useFormAction(createUser, (r) => r.data && onCreated(r.data), { quiet: true })
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="flex flex-col gap-4" noValidate>
      <Field label="Email" error={errors?.email}>
        {({ id, describedBy, invalid }) => (
          <input id={id} name="email" type="email" inputMode="email" autoComplete="off" required placeholder="name@nument.in" className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Full name" error={errors?.fullName}>
        {({ id, describedBy, invalid }) => <input id={id} name="fullName" autoComplete="off" required className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
      </Field>
      <Field label="Role" hint={ROLE_HINT[role]} error={errors?.role}>
        {({ id, describedBy }) => (
          <Select id={id} name="role" value={role} onChange={(e) => setRoleValue(e.target.value as Role)} aria-describedby={describedBy} className="w-full">
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
      <div>
        <Submit pending={pending}>Create account</Submit>
      </div>
    </form>
  )
}

function SecretSheet({ secret, onClose }: { secret: Secret | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <Sheet
      open={secret !== null}
      onOpenChange={(o) => {
        if (!o) {
          setCopied(false)
          onClose()
        }
      }}
    >
      <SheetContent title={secret?.title ?? ''} description="Shown once. Send it to them privately; they choose their own password when they sign in.">
        {secret ? (
          <div className="flex flex-col gap-4">
            <Panel>
              <Row label="Email">
                <span className="block truncate">{secret.email}</span>
              </Row>
              <Row label="Password">
                <code className="text-[15px] tracking-wide break-all tabular-nums select-all">{secret.tempPassword}</code>
              </Row>
            </Panel>
            <div>
              <Button
                onClick={() => {
                  void navigator.clipboard?.writeText(secret.tempPassword).then(() => setCopied(true))
                }}
              >
                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                {copied ? 'Copied' : 'Copy password'}
              </Button>
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
