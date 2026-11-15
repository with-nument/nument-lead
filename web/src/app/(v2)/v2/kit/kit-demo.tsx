'use client'

import { useId, useState } from 'react'
import { Copy, Ellipsis, Inbox, Phone, Plus, Share, Sun } from 'lucide-react'
import { ActivityIndicator } from '@/components/ui2/activity-indicator'
import { Button } from '@/components/ui2/button'
import { EmptyState } from '@/components/ui2/empty-state'
import { FieldGroup, FieldRow, fieldInput } from '@/components/ui2/field-group'
import { GradeMark } from '@/components/ui2/grade-mark'
import { GroupedList, ListRow } from '@/components/ui2/grouped-list'
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui2/popover'
import { SegmentedControl } from '@/components/ui2/segmented-control'
import { Select } from '@/components/ui2/select'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui2/sheet'
import { SkeletonList } from '@/components/ui2/skeleton'
import { StageLabel, STAGE_V2 } from '@/components/ui2/stage-label'
import { toast } from '@/components/ui2/toast'
import { Tooltip } from '@/components/ui2/tooltip'
import { WhoAnswers } from '@/components/ui2/who-answers'

const VIEWS = [
  { value: 'today', label: 'Today' },
  { value: 'week', label: 'This week' },
  { value: 'all', label: 'All' },
] as const

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="type-title px-1 text-label-1">{title}</h2>
      {children}
    </section>
  )
}

export function KitDemo() {
  const [view, setView] = useState<(typeof VIEWS)[number]['value']>('today')
  const id = useId()
  return (
    <div className="flex flex-col gap-12">
      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Primary</Button>
          <Button>Secondary</Button>
          <Button variant="plain">Plain</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="secondary" size="small">
            <Plus aria-hidden />
            Small
          </Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
        </div>
      </Section>

      <Section title="Segmented control">
        <SegmentedControl label="Show" items={VIEWS} value={view} onValueChange={setView} className="max-w-sm" />
        <p className="type-subhead px-1 text-label-3">Showing: {VIEWS.find((v) => v.value === view)?.label}</p>
      </Section>

      <Section title="Grouped list">
        <GroupedList header="Sample section" footer="A footnote explains the section in one line.">
          <ListRow href="/v2/kit" icon={<Sun />} title="Row with an icon" subtitle="A secondary line in tertiary text" detail="12" />
          <ListRow href="/v2/kit" icon={<Inbox />} title="Another row" accessory={<StageLabel stage="talking" className="text-label-2" />} />
          <ListRow onClick={() => toast('Row tapped')} icon={<Phone />} title="A button row" subtitle="Opens nothing, shows a toast" />
          <ListRow title="A plain row without an icon" detail="Detail" />
        </GroupedList>
      </Section>

      <Section title="Stages, grades and who answers">
        <GroupedList header="Stages">
          {Object.keys(STAGE_V2).map((s) => (
            <ListRow key={s} title={<StageLabel stage={s} />} detail={s} />
          ))}
        </GroupedList>
        <div className="material-panel flex flex-wrap items-center gap-6 rounded-panel px-4 py-3">
          {(['A', 'B', 'C', 'D'] as const).map((g) => (
            <span key={g} className="flex items-center gap-2">
              <GradeMark grade={g} />
              <GradeMark grade={g} size="large" />
            </span>
          ))}
        </div>
        <GroupedList header="Who answers">
          <ListRow title={<WhoAnswers line="owner" />} subtitle="Number on the owner's own page" />
          <ListRow title={<WhoAnswers line="front_desk" />} subtitle="Reception or the WhatsApp button" />
          <ListRow title={<WhoAnswers line="bot" />} subtitle="A vendor line or helpline" />
          <ListRow title={<WhoAnswers line="other" />} />
        </GroupedList>
      </Section>

      <Section title="Overlays">
        <div className="flex flex-wrap items-center gap-3">
          <Sheet>
            <SheetTrigger asChild>
              <Button>Open a sheet</Button>
            </SheetTrigger>
            <SheetContent title="Sample sheet" description="Rises from the bottom on phones, slides in on laptops.">
              <GroupedList label="Sample">
                <ListRow title="First option" chevron />
                <ListRow title="Second option" chevron />
              </GroupedList>
            </SheetContent>
          </Sheet>
          <Menu>
            <MenuTrigger asChild>
              <Button aria-label="More actions">
                <Ellipsis aria-hidden />
              </Button>
            </MenuTrigger>
            <MenuContent align="start">
              <MenuItem onSelect={() => toast('Copied')}>
                <Copy aria-hidden />
                Copy
              </MenuItem>
              <MenuItem>
                <Share aria-hidden />
                Share
              </MenuItem>
              <MenuSeparator />
              <MenuItem destructive>Remove</MenuItem>
            </MenuContent>
          </Menu>
          <Popover>
            <PopoverTrigger asChild>
              <Button>Popover</Button>
            </PopoverTrigger>
            <PopoverContent label="Sample popover">
              <p className="type-headline">A short note</p>
              <p className="type-subhead mt-1 text-label-3">Popovers hold a little detail next to what opened them.</p>
            </PopoverContent>
          </Popover>
          <Tooltip label="A hint on hover or focus">
            <Button variant="plain">Tooltip</Button>
          </Tooltip>
        </div>
      </Section>

      <Section title="Fields">
        <FieldGroup className="max-w-md">
          <FieldRow label="Name" htmlFor={`${id}-name`}>
            <input id={`${id}-name`} className={fieldInput} placeholder="Placeholder" />
          </FieldRow>
          <FieldRow label="City" htmlFor={`${id}-city`}>
            <input id={`${id}-city`} className={fieldInput} defaultValue="Pune" />
          </FieldRow>
        </FieldGroup>
        <Select aria-label="Sample choice" defaultValue="b" className="max-w-xs">
          <option value="a">First choice</option>
          <option value="b">Second choice</option>
        </Select>
      </Section>

      <Section title="Feedback">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => toast('Saved')}>Toast</Button>
          <Button onClick={() => toast.success('Marked as contacted', { action: { label: 'Undo', onClick: () => toast('Undone') } })}>Toast with undo</Button>
          <Button onClick={() => toast.error('Could not save. Try again.')}>Error toast</Button>
          <span className="flex items-center gap-2 text-label-3">
            <ActivityIndicator />
            Loading
          </span>
        </div>
        <SkeletonList rows={2} />
        <div className="material-panel rounded-panel">
          <EmptyState icon={<Inbox />} title="Nothing waiting" action={<Button variant="primary">One action</Button>}>
            One calm sentence about what will appear here.
          </EmptyState>
        </div>
      </Section>
    </div>
  )
}
