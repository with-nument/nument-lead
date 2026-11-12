// Lead stages (plan A.12.2). Stored in snake case, shown with the label. Colours match the sheet.
export const STAGES = [
  { value: 'new', label: 'New', closed: false, bg: '#F2F2F2', fg: '#525252' },
  { value: 'contacted', label: 'Contacted', closed: false, bg: '#E8EFFC', fg: '#212191' },
  { value: 'talking', label: 'Talking', closed: false, bg: '#D2DFF9', fg: '#11115B' },
  { value: 'discovery_booked', label: 'Discovery booked', closed: false, bg: '#FCEAF0', fg: '#9D2055' },
  { value: 'discovery_done', label: 'Discovery done', closed: false, bg: '#F9D5E1', fg: '#871F4B' },
  { value: 'proposal_sent', label: 'Proposal sent', closed: false, bg: '#FFF0CF', fg: '#8A5A00' },
  { value: 'won', label: 'Won', closed: true, bg: '#E3F1D8', fg: '#385418' },
  { value: 'retainer', label: 'Retainer', closed: true, bg: '#D9F0EA', fg: '#0F5C52' },
  { value: 'lost', label: 'Lost', closed: true, bg: '#FDE7E2', fg: '#A21913' },
  { value: 'not_now', label: 'Not now', closed: true, bg: '#FEEDE6', fg: '#A5460F' },
  { value: 'not_a_fit', label: 'Not a fit', closed: true, bg: '#F5F5F5', fg: '#666666' },
  { value: 'wrong_contact', label: 'Wrong contact', closed: true, bg: '#F3EEE8', fg: '#7A5536' },
] as const

export type StageInfo = (typeof STAGES)[number]
export type Stage = StageInfo['value']

export const STAGE_VALUES = STAGES.map((s) => s.value) as [Stage, ...Stage[]]
export const stageOf = (v: string | null | undefined): StageInfo => STAGES.find((s) => s.value === v) ?? STAGES[0]
export const isStage = (v: unknown): v is Stage => typeof v === 'string' && STAGE_VALUES.includes(v as Stage)
export const OPEN_STAGES = STAGES.filter((s) => !s.closed).map((s) => s.value)
export const CLOSED_STAGES = STAGES.filter((s) => s.closed).map((s) => s.value)
/** Stages that count as a deal won (money is recorded on these). */
export const WON_STAGES: readonly Stage[] = ['won', 'retainer']
/** Pipeline board: every stage except New (new leads live on Today). */
export const BOARD_STAGES = STAGES.filter((s) => s.value !== 'new')
/** PostgREST list for "not in closed stages" filters. */
export const CLOSED_STAGE_LIST = `(${CLOSED_STAGES.join(',')})`
