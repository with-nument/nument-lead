/** Why a phone, email or website is on Do not contact (plan A.12.1). */
export const SUPPRESSION_REASONS = ['opt_out', 'wrong_contact', 'competitor', 'founder_skip', 'legal'] as const
export type SuppressionReason = (typeof SUPPRESSION_REASONS)[number]

export const SUPPRESSION_REASON_LABEL: Record<string, string> = {
  opt_out: 'Asked not to be contacted',
  wrong_contact: 'Wrong contact',
  competitor: 'Competitor',
  founder_skip: 'Skipped by the founder',
  legal: 'Legal reason',
}
