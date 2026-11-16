'use client'

import Link from 'next/link'
import { Ellipsis } from 'lucide-react'
import { Button } from '@/components/ui2/button'
import { GradeMark } from '@/components/ui2/grade-mark'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui2/menu'
import { Note, TodayRow, Who } from './section'
import type { StartupItem } from './types'

export type StartupAction = 'sent' | 'replied' | 'skip'

/** The opened list of new startups: grade, name, why now, and Mark contacted with More (replied, skip, open). */
export function StartupsList({ items, canEdit, onAct }: { items: StartupItem[]; canEdit: boolean; onAct: (s: StartupItem, kind: StartupAction) => void }) {
  return (
        <div id="startups-list" className="[&>*+*]:hairline-t">
          {items.map((s) => (
            <TodayRow
              key={s.leadId}
              className="bg-row-done"
              action={
                canEdit ? (
                  <>
                    <Button onClick={() => onAct(s, 'sent')}>Mark contacted</Button>
                    <Menu>
                      <MenuTrigger aria-label={`More for ${s.company}`} className="grid size-11 shrink-0 place-items-center rounded-control text-label-2 hover:bg-fill-3 max-lg:!flex-none lg:size-[38px]">
                        <Ellipsis aria-hidden className="size-[18px]" strokeWidth={1.6} />
                      </MenuTrigger>
                      <MenuContent>
                        <MenuItem onSelect={() => onAct(s, 'replied')}>They replied</MenuItem>
                        <MenuItem onSelect={() => onAct(s, 'skip')}>Skip for now</MenuItem>
                        <MenuItem asChild>
                          <Link href={`/leads/${s.leadId}`}>Open the lead</Link>
                        </MenuItem>
                      </MenuContent>
                    </Menu>
                  </>
                ) : (
                  <Link href={`/leads/${s.leadId}`} className="text-[14px] text-label-1 underline decoration-separator-strong underline-offset-[3px]">
                    Open
                  </Link>
                )
              }
            >
              <GradeMark grade={s.grade} />
              <div className="min-w-0 flex-1">
                <Who main={s.company} sub={[s.person, s.city].filter(Boolean).join(', ') || null} />
                {s.signal ? <Note>{s.signal}</Note> : null}
              </div>
            </TodayRow>
          ))}
        </div>
  )
}
