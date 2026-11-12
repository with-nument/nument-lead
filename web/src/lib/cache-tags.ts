/**
 * Tags for the few reads that are the same for every signed-in user and rarely change, cached on the
 * server with `use cache` (src/lib/queries/shared.ts, shell.ts, engine.ts). The Server Actions that
 * change them call `updateTag(...)`, so the next page shows the change at once.
 * Nothing per user, nothing money-related and nothing that Row Level Security narrows by role is cached.
 */
export const TAGS = {
  /** segments: labels, countries, switches and quotas (Engine page actions). */
  segments: 'segments',
  /** profiles: team names and roles (Settings name change, Users and roles). */
  team: 'team',
  /** settings: the budget keys (Engine budget form). */
  budget: 'settings-budget',
  /** runs: the last sheet sync time in the top bar (written by the engine, so time-based only). */
  sheetSync: 'sheet-sync',
} as const
