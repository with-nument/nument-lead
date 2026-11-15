import type { Metadata } from 'next'
import { Sun } from 'lucide-react'
import { Placeholder } from '@/components/shell2/placeholder'
import { TodayDate } from '@/components/shell2/today-date'

export const metadata: Metadata = { title: 'Today' }

export default function TodayPage() {
  return (
    <Placeholder title="Today" eyebrow={<TodayDate />} icon={<Sun />} heading="The new Today is on its way">
      Until it is ready, your send list and follow-ups are in the classic design.
    </Placeholder>
  )
}
