import 'server-only'
import { z } from 'zod'

const ServerEnv = z.object({
  APP_ENV: z.enum(['dev', 'prod']).default('dev'),
  NEXT_PUBLIC_SUPABASE_URL: z.url(),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z.string().min(20),
  NEXT_PUBLIC_APP_URL: z.url().optional(),
  SUPABASE_URL: z.url().optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(20).optional(),
  GH_REPO: z
    .string()
    .regex(/^[\w.-]+\/[\w.-]+$/)
    .optional(),
  GH_DISPATCH_TOKEN: z.string().optional(),
  GH_DISPATCH_REF: z.string().min(1).default('main'),
})

export type ServerEnv = z.infer<typeof ServerEnv>

let cached: ServerEnv | null = null

/** Validated server environment. Read lazily so a missing optional secret never breaks the build. */
export function env(): ServerEnv {
  if (cached) return cached
  const parsed = ServerEnv.safeParse({
    ...process.env,
    // Empty strings in .env files mean "not set".
    GH_DISPATCH_TOKEN: process.env.GH_DISPATCH_TOKEN || undefined,
    GH_REPO: process.env.GH_REPO || undefined,
    SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY || undefined,
    NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL || undefined,
    SUPABASE_URL: process.env.SUPABASE_URL || undefined,
  })
  if (!parsed.success) {
    const fields = parsed.error.issues.map((i) => i.path.join('.')).join(', ')
    throw new Error(`Missing or invalid environment variables: ${fields}. See web/.env.example.`)
  }
  cached = parsed.data
  return cached
}
