import 'server-only'
import { createClient } from '@/lib/supabase/server'
import { boardFiltersJson, toBoard, type Board, type BoardFilters } from './page-data'

export type { Board, BoardCard, BoardFilters } from './page-data'

/** Cards per open stage before the rest are left out (the counts still say how many there are). */
export const BOARD_MAX_PER_STAGE = 500

/**
 * The pipeline in one database call (deals_board, migration 0024): every lead in an open stage (Contacted to
 * Proposal sent, at most `maxPerStage` per stage, most recently active first), a count per stage, and, only when
 * asked for, the most recent `closedPerStage` cards of each closed stage. New leads live on Today. Runs as the
 * user (Row Level Security), so the page can start it before the role is known; admins get the money on the
 * cards that have any.
 *
 * Before, the board read 1,000 rows across every stage, newest activity first: once enough leads had closed,
 * real deals with older activity were cut off.
 */
export async function getBoard(f: BoardFilters, opts: { maxPerStage?: number; closedPerStage?: number } = {}): Promise<Board> {
  const sb = await createClient()
  const { data, error } = await sb.rpc('deals_board', {
    filters: boardFiltersJson(f),
    max_per_stage: opts.maxPerStage ?? BOARD_MAX_PER_STAGE,
    closed_per_stage: opts.closedPerStage ?? 0,
  })
  if (error) throw error
  return toBoard(data)
}
