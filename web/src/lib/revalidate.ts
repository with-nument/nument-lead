import 'server-only'
import { revalidatePath } from 'next/cache'

/** Every page that shows a lead, so a change made anywhere shows everywhere. */
export function revalidateLead(leadId?: string) {
  revalidatePath('/')
  revalidatePath('/leads')
  if (leadId) revalidatePath(`/leads/${leadId}`)
  revalidatePath('/pipeline')
  revalidatePath('/insights')
}
