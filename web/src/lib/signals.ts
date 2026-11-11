// Signal types (plan A.12.3) with plain labels for the app.
export const SIGNAL_TYPES = [
  { value: 'public_ask', label: 'Asked for help publicly', category: 'stated_need' },
  { value: 'tender', label: 'Tender or RFP', category: 'stated_need' },
  { value: 'hiring_builder', label: 'Hiring a developer', category: 'stated_need' },
  { value: 'hiring_frontdesk', label: 'Hiring front desk staff', category: 'visible_pain' },
  { value: 'review_pain', label: 'Reviews mention slow replies', category: 'visible_pain' },
  { value: 'ads_running', label: 'Running ads', category: 'visible_pain' },
  { value: 'no_booking', label: 'No online booking', category: 'visible_pain' },
  { value: 'slow_site', label: 'Slow mobile site', category: 'visible_pain' },
  { value: 'new_place', label: 'New business', category: 'growth' },
  { value: 'new_branch', label: 'Opened a new branch', category: 'growth' },
  { value: 'news', label: 'In the news', category: 'growth' },
  { value: 'funding', label: 'Raised funding', category: 'money' },
] as const

export type SignalType = (typeof SIGNAL_TYPES)[number]['value']
export const SIGNAL_VALUES = SIGNAL_TYPES.map((s) => s.value) as [SignalType, ...SignalType[]]
export const signalLabel = (v: string | null | undefined) =>
  SIGNAL_TYPES.find((s) => s.value === v)?.label ?? (v ? v.replaceAll('_', ' ') : 'No signal')

export const PITCH_MODES = [
  { value: 'stated_need', label: 'Stated need' },
  { value: 'visible_pain', label: 'Visible pain' },
  { value: 'fit_only', label: 'Fit only' },
] as const
export type PitchMode = (typeof PITCH_MODES)[number]['value']
export const PITCH_VALUES = PITCH_MODES.map((p) => p.value) as [PitchMode, ...PitchMode[]]
export const pitchLabel = (v: string | null | undefined) => PITCH_MODES.find((p) => p.value === v)?.label ?? ''

export const PHONE_TYPE_LABEL: Record<string, string> = {
  mobile: 'mobile',
  landline: 'landline',
  tollfree: 'toll free',
  unknown: 'phone',
}
export const CONTACT_SOURCE_LABEL: Record<string, string> = {
  website: 'website',
  google_listing: 'Google listing',
  registry: 'registry',
  other: 'other source',
}

export const COUNTRY_LABEL: Record<string, string> = { in: 'India', ae: 'UAE' }
export const countryLabel = (v: string | null | undefined) => (v ? (COUNTRY_LABEL[v.trim().toLowerCase()] ?? v.toUpperCase()) : '')

/** "clinics-in" becomes "Clinics, India" when the segment row is not at hand. */
export function segmentFallbackLabel(id: string | null | undefined) {
  if (!id) return ''
  const [domain, country] = id.split('-')
  const d = domain ? domain.charAt(0).toUpperCase() + domain.slice(1) : id
  return country ? `${d}, ${countryLabel(country)}` : d
}
