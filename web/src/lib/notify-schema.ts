// The inputs of Settings > Email recipients actions, checked on the server. Server-only on purpose: zod is
// large, and lib/notify.ts (labels and the test email) is imported by a client component.
import 'server-only'
import { z } from 'zod'
import { RECIPIENT_FIELDS } from '@/lib/notify'

export const NewRecipient = z.object({
  email: z.string().trim().toLowerCase().max(254, 'Use at most 254 characters.').pipe(z.email('Enter a valid email.')),
  name: z
    .string()
    .trim()
    .max(80, 'Use at most 80 characters.')
    .transform((v) => v || null),
})

export const RecipientToggle = z.object({
  id: z.uuid(),
  field: z.enum(RECIPIENT_FIELDS),
  value: z.boolean(),
})
