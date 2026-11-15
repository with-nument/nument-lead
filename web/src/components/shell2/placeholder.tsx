import Link from 'next/link'
import { buttonClass } from '@/components/ui2/button'
import { EmptyState } from '@/components/ui2/empty-state'
import { Page } from '@/components/ui2/large-title'
import { ClassicDesignButton } from './classic-design-button'

/**
 * A v2 page that is not built yet: the real header, then one calm note and one way forward, either
 * the current-design page that does the job today or a switch back to the classic design.
 */
export function Placeholder({
  title,
  icon,
  heading,
  children,
  classicHref,
  classicLabel,
  eyebrow,
}: {
  title: string
  icon: React.ReactNode
  heading: string
  children: React.ReactNode
  /** A current-design page that does this job today (not on the v2 list, so it opens as it is). */
  classicHref?: string
  classicLabel?: string
  eyebrow?: React.ReactNode
}) {
  return (
    <Page title={title} eyebrow={eyebrow}>
      <EmptyState
        icon={icon}
        title={heading}
        action={
          classicHref ? (
            <Link href={classicHref} className={buttonClass('secondary')}>
              {classicLabel}
            </Link>
          ) : (
            <ClassicDesignButton />
          )
        }
      >
        {children}
      </EmptyState>
    </Page>
  )
}
