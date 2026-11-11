/** Reasons for thumbs up or down on a lead. They feed the weekly report and the golden set. */
export const FEEDBACK_REASONS = [
  'Great lead',
  'Wrong segment',
  'Cannot pay',
  'No real need',
  'Wrong contact',
  'Already has a vendor',
  'Other',
] as const
export type FeedbackReason = (typeof FEEDBACK_REASONS)[number]
