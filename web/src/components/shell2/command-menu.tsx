'use client'

import { useEffect, useId, useMemo, useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Dialog as D } from 'radix-ui'
import { CornerDownLeft } from 'lucide-react'
import { searchLeadsAction } from '@/app/(v2)/v2/search-actions'
import { Kbd } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { GradeMark } from '@/components/ui2/grade-mark'
import { StageLabel } from '@/components/ui2/stage-label'
import type { Role } from '@/lib/roles'
import type { SearchResult } from '@/lib/queries/page-data'
import { setCommandMenuOpen, useCommandMenuOpen } from './command-store'
import { SearchIcon } from './icons'
import { PRIMARY_NAV, secondaryFor, type NavItem } from './nav-items'

type Option = { key: string; href: string; kind: 'lead'; lead: SearchResult } | { key: string; href: string; kind: 'page'; page: NavItem }

const DEBOUNCE_MS = 160

/** Lower-case words of a query, for matching page names. */
const words = (q: string) => q.toLowerCase().split(/\s+/).filter(Boolean)

/**
 * The ⌘K command menu: find a lead by name, website or phone, or go to a page. Opens from the sidebar search
 * box, the phone search button, ⌘K or Ctrl+K. Arrow keys move, Enter opens, Escape closes. Loaded on first
 * use by CommandMenuHost, so it adds nothing to a page's first load.
 */
export function CommandMenu({ role = null }: { role?: Role | null }) {
  const open = useCommandMenuOpen()
  const router = useRouter()
  const listId = useId()
  const [query, setQuery] = useState('')
  const [leads, setLeads] = useState<SearchResult[]>([])
  const [failed, setFailed] = useState(false)
  const [active, setActive] = useState(0)
  const [searching, startSearch] = useTransition()
  const latest = useRef('')

  // Leads, a moment after typing stops. Only the newest answer counts.
  useEffect(() => {
    const term = query.trim()
    latest.current = term
    if (term.length < 2) return
    const t = window.setTimeout(() => {
      startSearch(async () => {
        const answer = await searchLeadsAction(term)
        if (latest.current !== term) return
        setLeads(answer.results)
        setFailed(!answer.ok)
        setActive(0)
      })
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(t)
  }, [query])

  const term = query.trim()
  const shownLeads = term.length >= 2 ? leads : []
  const pages = useMemo(() => {
    const all = [...PRIMARY_NAV, ...secondaryFor(role)]
    const q = words(term)
    return q.length ? all.filter((p) => q.every((w) => p.label.toLowerCase().includes(w))) : all
  }, [term, role])

  const options: Option[] = [
    ...shownLeads.map((lead): Option => ({ key: `lead-${lead.id}`, href: `/leads/${lead.id}`, kind: 'lead', lead })),
    ...pages.map((page): Option => ({ key: `page-${page.href}`, href: page.href, kind: 'page', page })),
  ]
  const current = Math.min(active, Math.max(0, options.length - 1))

  function close() {
    setCommandMenuOpen(false)
  }

  function onOpenChange(next: boolean) {
    setCommandMenuOpen(next)
    if (!next) {
      setQuery('')
      setLeads([])
      setFailed(false)
      setActive(0)
    }
  }

  function go(option: Option | undefined) {
    if (!option) return
    onOpenChange(false)
    router.push(option.href)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((current + 1) % Math.max(1, options.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((current - 1 + options.length) % Math.max(1, options.length))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      go(options[current])
    }
  }

  const optionId = (i: number) => `${listId}-${i}`
  const leadStatus =
    term.length < 2
      ? null
      : searching && !shownLeads.length
        ? 'Searching leads…'
        : failed
          ? 'Lead search is not answering. Try again in a moment.'
          : !shownLeads.length
            ? `No lead matches “${term}”. Try part of the name or the website.`
            : null

  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay data-ui-motion className="motion-fade fixed inset-0 z-50 bg-scrim" />
        <D.Content
          data-ui-motion
          aria-describedby={undefined}
          className={cx(
            'ui2-base motion-pop material-overlay fixed z-50 flex flex-col overflow-hidden outline-none',
            'inset-x-3 top-[max(12px,env(safe-area-inset-top))] max-h-[calc(100dvh-24px)] rounded-panel',
            'lg:inset-x-auto lg:top-[14vh] lg:left-1/2 lg:max-h-[min(560px,72vh)] lg:w-[620px] lg:-translate-x-1/2',
          )}
        >
          <D.Title className="sr-only">Search</D.Title>
          <div className="flex h-14 shrink-0 items-center gap-3 border-b border-separator px-[18px]">
            <SearchIcon className="size-[18px] shrink-0 text-label-3" />
            <input
              autoFocus
              role="combobox"
              aria-expanded
              aria-controls={listId}
              aria-activedescendant={options.length ? optionId(current) : undefined}
              aria-autocomplete="list"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(0)
              }}
              onKeyDown={onKeyDown}
              placeholder="Search leads by name or website, or go to a page"
              className="h-full min-w-0 flex-1 bg-transparent text-[16px] text-label-1 outline-none placeholder:text-label-4 focus-visible:outline-none"
            />
            <button type="button" onClick={close} className="rounded-[6px] max-lg:hidden" aria-label="Close">
              <Kbd>esc</Kbd>
            </button>
            <button type="button" onClick={close} className="-mr-2 h-11 px-2 text-[15px] text-label-2 lg:hidden">
              Cancel
            </button>
          </div>
          <div id={listId} role="listbox" aria-label="Results" className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2">
            {term.length >= 2 ? <GroupLabel>Leads</GroupLabel> : null}
            {leadStatus ? <p className="px-3 pt-1 pb-3 text-[14px] text-label-3">{leadStatus}</p> : null}
            {options.map((option, i) => (
              <div key={option.key}>
                {option.kind === 'page' && (i === 0 || options[i - 1]?.kind !== 'page') ? <GroupLabel>Go to</GroupLabel> : null}
                <div
                  id={optionId(i)}
                  role="option"
                  aria-selected={i === current}
                  onMouseMove={() => i !== current && setActive(i)}
                  onClick={() => go(option)}
                  className={cx(
                    'flex min-h-12 cursor-default items-center gap-3 rounded-[10px] px-3 text-[15px] lg:min-h-11',
                    i === current ? 'bg-fill-2' : null,
                  )}
                >
                  {option.kind === 'lead' ? <LeadOption lead={option.lead} /> : <PageOption page={option.page} />}
                  {i === current ? <CornerDownLeft aria-hidden className="size-4 shrink-0 text-label-3 max-lg:hidden" strokeWidth={1.6} /> : null}
                </div>
              </div>
            ))}
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return <p className="px-3 pt-2 pb-1.5 text-[12px] font-medium text-label-3">{children}</p>
}

function LeadOption({ lead }: { lead: SearchResult }) {
  const where = lead.webDomain ?? [lead.city, lead.country].filter(Boolean).join(', ')
  return (
    <>
      <GradeMark grade={lead.grade} />
      <span className="min-w-0 flex-1 truncate">
        <span className="font-[550] text-label-1">{lead.name}</span>
        {where ? <span className="text-label-3"> · {where}</span> : null}
      </span>
      <StageLabel stage={lead.stage} className="max-sm:hidden" />
    </>
  )
}

function PageOption({ page }: { page: NavItem }) {
  const Icon = page.icon
  return (
    <>
      <span className="grid size-6 place-items-center text-label-2">
        <Icon className="size-[18px]" />
      </span>
      <span className="flex-1 text-label-1">{page.label}</span>
    </>
  )
}
