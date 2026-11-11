// The "must change password" flag lives in app_metadata. Signed-in users can edit their own
// user_metadata (auth.updateUser({ data })), so a flag there could be cleared by the user and the
// forced change skipped. app_metadata can only be changed with the service role.

export const MUST_CHANGE_KEY = 'must_change_password'

/** True only when app_metadata carries the flag as boolean true. user_metadata is never read. */
export function mustChangePassword(appMetadata: unknown): boolean {
  return Boolean(appMetadata && typeof appMetadata === 'object' && (appMetadata as Record<string, unknown>)[MUST_CHANGE_KEY] === true)
}

/**
 * Admin-API update that sets the flag in app_metadata (merged, so provider keys stay) and removes
 * any old copy from user_metadata (Supabase deletes keys set to null).
 */
export function flagUpdate(appMetadata: Record<string, unknown> | undefined, value: boolean) {
  return {
    app_metadata: { ...(appMetadata ?? {}), [MUST_CHANGE_KEY]: value },
    user_metadata: { [MUST_CHANGE_KEY]: null },
  }
}
