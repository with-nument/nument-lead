export const ROLES = ['admin', 'caller', 'viewer'] as const
export type Role = (typeof ROLES)[number]

export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Admin',
  caller: 'Caller',
  viewer: 'Viewer',
}

export const ROLE_HINT: Record<Role, string> = {
  admin: 'Everything, including money, engine settings and users.',
  caller: 'Sends messages and moves leads. Never sees money.',
  viewer: 'Read only. Never sees money.',
}

/** Only admins ever see deal values. Callers and viewers read leads through a view without money. */
export const canSeeMoney = (role: Role) => role === 'admin'
/** Admins and callers can change leads. Viewers read only. */
export const canEdit = (role: Role) => role === 'admin' || role === 'caller'
export const isRole = (v: unknown): v is Role => typeof v === 'string' && (ROLES as readonly string[]).includes(v)
