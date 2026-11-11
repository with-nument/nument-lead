// Lead grades (plan A.12.9): A 70+, B 55 to 69, C 40 to 54, D under 40.
export const GRADES = ['A', 'B', 'C', 'D'] as const
export type Grade = (typeof GRADES)[number]

export const GRADE_STYLE: Record<Grade, { bg: string; fg: string }> = {
  A: { bg: '#E3F1D8', fg: '#496D21' },
  B: { bg: '#E8EFFC', fg: '#3333CC' },
  C: { bg: '#F5F5F5', fg: '#666666' },
  D: { bg: '#FAFAFA', fg: '#666666' },
}

export const isGrade = (v: unknown): v is Grade => typeof v === 'string' && (GRADES as readonly string[]).includes(v)
export const gradeOf = (v: string | null | undefined): Grade => (isGrade(v?.trim()) ? (v!.trim() as Grade) : 'D')
