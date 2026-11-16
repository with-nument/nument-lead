import { DealsBoard } from '../../../deals/_board/deals-board'
import { boardView, previewOnly } from '../fixtures'

/** Preview: the Deals board (sample data). */
export default function DealsPreview() {
  previewOnly()
  return <DealsBoard view={boardView()} canEdit isAdmin />
}
