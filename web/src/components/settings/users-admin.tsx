'use client'

import { useActionState, useState, useTransition } from 'react'
import { Ellipsis, KeyRound, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { createUser, resetPasswordForUser, setDisabled, setRole, type CreatedUser } from '@/app/(app)/settings/users/actions'
import { Tag } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/dropdown-menu'
import { Field } from '@/components/ui/field'
import { Input, Select } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import type { ActionResult } from '@/lib/action-result'
import { ROLE_HINT, ROLE_LABEL, ROLES, type Role } from '@/lib/roles'

export type UserRow = {
  id: string
  name: string
  email: string
  role: Role | null
  lastSignIn: string
  disabled: boolean
  mustChangePassword: boolean
  isMe: boolean
}

function TempPassword({ email, password }: { email: string; password: string }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-base text-tx-2">
        Share this temporary password with <span className="font-medium text-tx-1">{email}</span> in person or on a private chat. It is shown only once. They must choose their own password when they first sign in.
      </p>
      <div className="flex items-center gap-2 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
        <code className="min-w-0 flex-1 font-mono text-md break-all text-tx-1" data-testid="temp-password">
          {password}
        </code>
        <CopyButton text={password} size="sm" variant="secondary" toastMessage="Password copied" />
      </div>
    </div>
  )
}

export function CreateUserButton() {
  const [open, setOpen] = useState(false)
  const [state, action] = useActionState<ActionResult<CreatedUser> | undefined, FormData>(createUser, undefined)
  const created = state?.ok ? state.data : undefined
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="primary">
          <UserPlus aria-hidden />
          Create user
        </Button>
      </DialogTrigger>
      <DialogContent title={created ? 'User created' : 'Create a user'} description={created ? undefined : 'There is no public sign-up. Only admins add people.'}>
        {created ? (
          <div className="flex flex-col gap-4">
            <TempPassword email={created.email} password={created.tempPassword} />
            <div className="flex justify-end">
              <Button variant="primary" onClick={() => setOpen(false)}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <form action={action} className="flex flex-col gap-4" key={open ? 'open' : 'closed'}>
            <Field label="Full name" error={errors?.fullName}>
              {({ id, describedBy, invalid }) => <Input id={id} name="fullName" required autoComplete="off" aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
            </Field>
            <Field label="Email" error={errors?.email}>
              {({ id, describedBy, invalid }) => <Input id={id} name="email" type="email" required autoComplete="off" aria-describedby={describedBy} aria-invalid={invalid || undefined} />}
            </Field>
            <Field label="Role" hint="Callers and viewers never see money.">
              {({ id, describedBy }) => (
                <Select id={id} name="role" defaultValue="caller" aria-describedby={describedBy}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}: {ROLE_HINT[r]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {state && !state.ok && !state.fieldErrors ? <p className="text-sm text-bad">{state.message}</p> : null}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <SubmitButton>Create user</SubmitButton>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function UsersTable({ users }: { users: UserRow[] }) {
  const [pending, start] = useTransition()
  const [reset, setReset] = useState<{ email: string; password: string } | null>(null)
  const run = (fn: () => Promise<ActionResult>) =>
    start(async () => {
      const r = await fn()
      if (r.ok) toast(r.message ?? 'Saved')
      else toast.error(r.message)
    })
  const th = 'label-mono h-10 border-b border-line-2 px-3 font-normal whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5'
  const td = 'h-14 px-3 align-middle first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5'
  return (
    <>
      <div className="relative overflow-x-auto">
        <table className="w-full text-left text-base">
          <thead>
            <tr>
              <th scope="col" className={th}>User</th>
              <th scope="col" className={th}>Role</th>
              <th scope="col" className={th}>Last sign in</th>
              <th scope="col" className={th}>Status</th>
              <th scope="col" className={th}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-line-2 last:border-b-0">
                <td className={td}>
                  <div className="text-tx-1">
                    {u.name}
                    {u.isMe ? <span className="text-tx-3"> (you)</span> : null}
                  </div>
                  <div className="text-sm text-tx-3">{u.email}</div>
                </td>
                <td className={td}>
                  <label className="sr-only" htmlFor={`role-${u.id}`}>
                    Role for {u.name}
                  </label>
                  <div className="w-32">
                    <Select
                      id={`role-${u.id}`}
                      defaultValue={u.role ?? ''}
                      disabled={pending || u.isMe}
                      className="h-9"
                      onChange={(e) => {
                        const role = e.currentTarget.value
                        run(() => setRole({ userId: u.id, role }))
                      }}
                    >
                      {!u.role ? <option value="">No role</option> : null}
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABEL[r]}
                        </option>
                      ))}
                    </Select>
                  </div>
                </td>
                <td className={`${td} whitespace-nowrap text-tx-3`}>{u.lastSignIn || 'Never'}</td>
                <td className={td}>
                  {u.disabled ? <Tag tone="bad">Disabled</Tag> : u.mustChangePassword ? <Tag tone="warn">Temporary password</Tag> : <Tag tone="ok">Active</Tag>}
                </td>
                <td className={`${td} text-right`}>
                  {!u.isMe ? (
                    <Menu>
                      <MenuTrigger asChild>
                        <Button size="icon-sm" variant="ghost" aria-label={`Actions for ${u.name}`} disabled={pending}>
                          <Ellipsis />
                        </Button>
                      </MenuTrigger>
                      <MenuContent>
                        <MenuItem
                          onSelect={() =>
                            start(async () => {
                              const r = await resetPasswordForUser({ userId: u.id })
                              if (r.ok && r.data) setReset({ email: u.email, password: r.data.tempPassword })
                              else toast.error(r.ok ? 'Could not reset the password.' : r.message)
                            })
                          }
                        >
                          <KeyRound aria-hidden />
                          Reset password
                        </MenuItem>
                        <MenuItem danger={!u.disabled} onSelect={() => run(() => setDisabled({ userId: u.id, disabled: !u.disabled }))}>
                          {u.disabled ? 'Enable account' : 'Disable account'}
                        </MenuItem>
                      </MenuContent>
                    </Menu>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Dialog open={Boolean(reset)} onOpenChange={(o) => !o && setReset(null)}>
        {reset ? (
          <DialogContent title="New temporary password">
            <div className="flex flex-col gap-4">
              <TempPassword email={reset.email} password={reset.password} />
              <div className="flex justify-end">
                <Button variant="primary" onClick={() => setReset(null)}>
                  Done
                </Button>
              </div>
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  )
}
