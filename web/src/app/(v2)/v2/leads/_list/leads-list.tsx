'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Fragment, useEffect, useMemo, useRef, useState, useTransition } from 'react'
import { ChevronLeft, ChevronRight, ListFilter, Search, SearchX } from 'lucide-react'
import { bulkAssignOwner, bulkSuppress, bulkUpdateStage } from '@/app/(app)/leads/actions'
import { buttonClass } from '@/components/ui2/button'
import { cx } from '@/components/ui2/cx'
import { EmptyState } from '@/components/ui2/empty-state'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/components/ui2/menu'
import { Sheet, SheetTrigger } from '@/components/ui2/sheet'
import { STAGE_V2, stageLabel } from '@/components/ui2/stage-label'
import { toast } from '@/components/ui2/toast'
import { formatNumber } from '@/lib/format'
import { filtersToQuery, type LeadFilters } from '@/lib/leads-filters'
import { needsLostReason, type LostReason } from '@/lib/outcomes'
import type { SavedView } from '@/lib/queries/page-data'
import { STAGE_VALUES, type Stage } from '@/lib/stages'
import { GradeLetter, outlineClass, panel, plainClass, Status } from '../_ui/marks'
import { ReasonSheet } from '../_ui/stage-move'
import { UndoRow, useUndo } from '../_ui/use-run'
import { FilterSheet, type FilterOptions } from './filter-sheet'
import { extraFilterCount, scopeFilters, scopeOf, SCOPES, type LeadRowV2 } from './model'

export type LeadsListProps = {
  rows: LeadRowV2[]
  filters: LeadFilters
  total: number
  pageSize: number
  /** Leads found since yesterday, for the New tab and the subtitle (null when unknown). */
  newCount: number | null
  options: FilterOptions
  views: { mine: SavedView[]; shared: SavedView[] }
  canEdit: boolean
  isAdmin: boolean
  canExport: boolean
}

const check = 'size-[18px] shrink-0 cursor-pointer accent-[var(--ui-label-2)]'
const href = (f: LeadFilters) => {
  const qs = filtersToQuery(f)
  return qs ? `/leads?${qs}` : '/leads'
}

/** The v2 Leads list: search, scope tabs, a filter sheet, a plain table and a bulk bar. */
export function LeadsList({ rows, filters, total, pageSize, newCount, options, views, canEdit, isAdmin, canExport }: LeadsListProps) {
  const router = useRouter()
  const [navigating, startNav] = useTransition()
  const [pending, start] = useTransition()
  const go = (f: LeadFilters) => startNav(() => router.push(href(f), { scroll: false }))
  const [q, setQ] = useState(filters.q)
  const [filterOpen, setFilterOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [cursor, setCursor] = useState(-1)
  const [local, setLocal] = useState<Record<string, string>>({})
  const [askReason, setAskReason] = useState<Stage | null>(null)
  const undo = useUndo()
  const tableRef = useRef<HTMLTableSectionElement>(null)
  const scope = scopeOf(filters)
  const extra = scope ? 0 : extraFilterCount(filters)

  // A new page of rows clears the selection and the keyboard cursor.
  const [rowsKey, setRowsKey] = useState(rows)
  if (rowsKey !== rows) {
    setRowsKey(rows)
    setSelected(new Set())
    setCursor(-1)
    setLocal({})
  }

  // Search as you type, a moment after the last key.
  useEffect(() => {
    if (q.trim() === filters.q) return
    const t = window.setTimeout(() => go({ ...filters, q: q.trim(), page: 1 }), 350)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const toggle = (id: string) =>
    setSelected((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  // J and K move through the rows, Enter opens one, X selects it, / jumps to search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault()
        setCursor((c) => {
          const n = Math.max(0, Math.min(rows.length - 1, c + (e.key === 'j' ? 1 : -1)))
          tableRef.current?.querySelectorAll<HTMLElement>('tr[data-row] a')[n]?.focus()
          return n
        })
      } else if (e.key === 'x' && cursor >= 0 && rows[cursor]) {
        toggle(rows[cursor]!.id)
      } else if (e.key === '/') {
        e.preventDefault()
        document.getElementById('leads-search')?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const ids = [...selected]
  const allOn = rows.length > 0 && selected.size === rows.length

  const moveSelected = (stage: Stage, reason?: LostReason) => {
    const before = rows.filter((r) => selected.has(r.id)).map((r) => ({ id: r.id, stage: local[r.id] ?? r.stage }))
    setLocal((cur) => ({ ...cur, ...Object.fromEntries(before.map((b) => [b.id, stage])) }))
    start(async () => {
      const r = await bulkUpdateStage({ ids: before.map((b) => b.id), stage, lostReason: reason ?? null })
      setAskReason(null)
      if (!r.ok) {
        setLocal((cur) => ({ ...cur, ...Object.fromEntries(before.map((b) => [b.id, b.stage])) }))
        toast.error(r.message)
        return
      }
      setSelected(new Set())
      // Undo puts each lead back where it was. Leads that were Lost or Not now keep their old reason only
      // through the lead page, so those are not offered an undo here.
      if (before.some((b) => needsLostReason(b.stage))) toast(r.message ?? 'Moved')
      else
        undo.offer(`${r.message ?? 'Moved'} to ${stageLabel(stage)}`, async () => {
          const groups = new Map<string, string[]>()
          for (const b of before) groups.set(b.stage, [...(groups.get(b.stage) ?? []), b.id])
          setLocal((cur) => ({ ...cur, ...Object.fromEntries(before.map((b) => [b.id, b.stage])) }))
          for (const [s, gids] of groups) {
            const u = await bulkUpdateStage({ ids: gids, stage: s })
            if (!u.ok) return u
          }
          return { ok: true, message: 'Moved back' }
        })
    })
  }
  const run = (fn: () => Promise<{ ok: boolean; message?: string }>) =>
    start(async () => {
      const r = await fn()
      if (r.ok) {
        toast(r.message ?? 'Saved')
        setSelected(new Set())
      } else toast.error(r.message ?? 'Could not save. Try again.')
    })

  const pages = Math.max(1, Math.ceil(total / pageSize))
  const page = Math.min(filters.page, pages)
  const exportHref = `/leads/export?${[filtersToQuery(filters), ...ids.map((id) => `ids=${id}`)].filter(Boolean).join('&')}`
  const subtitle = [`${formatNumber(total)} ${total === 1 ? 'lead' : 'leads'}${scope === 'all' ? '' : ' here'}`, newCount ? `${formatNumber(newCount)} found since yesterday` : null]
    .filter(Boolean)
    .join(' · ')

  const scopeLinks = useMemo(() => SCOPES.map((s) => ({ ...s, href: href(scopeFilters(s.value, filters.q)) })), [filters.q])

  return (
    <div className="mx-auto max-w-[1280px] px-4 pt-4 sm:px-6 lg:px-14 lg:pt-11">
      <header className="mb-5 flex items-end justify-between gap-6 lg:mb-8">
        <div className="min-w-0">
          <h1 className="text-[30px] leading-[1.15] font-semibold tracking-[-0.025em] text-label-1 lg:text-[32px]">Leads</h1>
          <p className="mt-1.5 text-[15px] text-label-3 lg:mt-2">{subtitle}</p>
        </div>
        {canExport ? (
          <a href={exportHref} download className={cx(outlineClass(), 'hidden sm:inline-flex')}>
            Export CSV
          </a>
        ) : null}
      </header>

      <div className="mb-4 flex flex-col gap-3 lg:mb-[22px] lg:flex-row lg:items-center lg:gap-[18px]">
        <label className="flex h-11 min-w-0 items-center gap-2.5 rounded-[14px] bg-panel px-4 text-label-3 hairline-ring focus-within:shadow-[inset_0_0_0_1.5px_var(--ui-label-2)] lg:h-[46px] lg:flex-1 lg:basis-[580px]">
          <Search aria-hidden className="size-4 shrink-0" strokeWidth={1.75} />
          <span className="sr-only">Search</span>
          <input
            id="leads-search"
            type="search"
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
            placeholder="Search company, founder or city"
            aria-keyshortcuts="/"
            className="h-full min-w-0 flex-1 bg-transparent text-[17px] text-label-1 outline-none placeholder:text-label-4 lg:text-[15px]"
          />
        </label>
        <div className="flex items-center gap-3">
          <nav aria-label="Scope" className="-mx-4 flex min-w-0 flex-1 overflow-x-auto px-4 lg:mx-0 lg:px-0">
            <div className="inline-flex gap-0.5 rounded-[12px] bg-fill-2 p-[3px]">
              {scopeLinks.map((s) => (
                <Link
                  key={s.value}
                  href={s.href}
                  scroll={false}
                  aria-current={scope === s.value ? 'page' : undefined}
                  className={cx(
                    'inline-flex h-[38px] items-center gap-1.5 rounded-[9px] px-3.5 text-[15px] whitespace-nowrap text-label-3 lg:h-8 lg:text-[14px]',
                    'hover:text-label-1 aria-[current=page]:bg-thumb aria-[current=page]:font-semibold aria-[current=page]:text-label-1 aria-[current=page]:shadow-[var(--ui-shadow-thumb)]',
                  )}
                >
                  {s.label}
                  {s.value === 'new' && newCount ? <span className="text-[13px] font-normal text-label-3">{formatNumber(newCount)}</span> : null}
                </Link>
              ))}
            </div>
          </nav>
          <Sheet open={filterOpen} onOpenChange={setFilterOpen}>
            <SheetTrigger className={cx(outlineClass(), 'lg:ml-auto lg:h-[46px] lg:rounded-[14px] lg:px-5')}>
              <ListFilter aria-hidden />
              <span className="hidden sm:inline">Filter</span>
              {extra ? <span className="text-label-3">{extra}</span> : null}
            </SheetTrigger>
            {filterOpen ? (
              <FilterSheet
                filters={filters}
                options={options}
                views={views}
                onApply={(f) => {
                  setFilterOpen(false)
                  go(f)
                }}
              />
            ) : null}
          </Sheet>
        </div>
      </div>

      <UndoRow undo={undo} className="mb-3" />

      <section aria-label="Leads" aria-busy={navigating || undefined} className={cx(panel, 'overflow-hidden transition-opacity', navigating && 'opacity-60')}>
        {selected.size ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-2 bg-fill-3 px-4 py-3 hairline-b lg:px-[26px]">
            <input type="checkbox" aria-label="Select all on this page" className={check} checked={allOn} onChange={() => setSelected(allOn ? new Set() : new Set(rows.map((r) => r.id)))} />
            <span className="ml-2 font-semibold text-label-1">{selected.size} selected</span>
            <span className="ml-auto" />
            {isAdmin ? (
              <Menu>
                <MenuTrigger className={plainClass('small')} disabled={pending}>
                  Owner…
                </MenuTrigger>
                <MenuContent>
                  <MenuItem onSelect={() => run(() => bulkAssignOwner({ ids, ownerId: null }))}>Nobody</MenuItem>
                  {options.team.map((m) => (
                    <MenuItem key={m.id} onSelect={() => run(() => bulkAssignOwner({ ids, ownerId: m.id }))}>
                      {m.name}
                    </MenuItem>
                  ))}
                </MenuContent>
              </Menu>
            ) : null}
            {isAdmin ? (
              <button type="button" disabled={pending} className={plainClass('small')} onClick={() => run(() => bulkSuppress({ ids }))}>
                Don&rsquo;t contact
              </button>
            ) : null}
            {canExport ? (
              <a href={exportHref} download className={plainClass('small')}>
                Export
              </a>
            ) : null}
            <button type="button" className={plainClass('small')} onClick={() => setSelected(new Set())}>
              Clear
            </button>
            {canEdit ? (
              <Menu>
                <MenuTrigger className={buttonClass('primary', 'small')} disabled={pending}>
                  Move {selected.size} to…
                </MenuTrigger>
                <MenuContent>
                  <MenuLabel>Move to</MenuLabel>
                  {STAGE_VALUES.map((s) => (
                    <Fragment key={s}>
                      {s === 'won' ? <MenuSeparator /> : null}
                      <MenuItem onSelect={() => (needsLostReason(s) ? setAskReason(s) : moveSelected(s))}>{STAGE_V2[s].label}</MenuItem>
                    </Fragment>
                  ))}
                </MenuContent>
              </Menu>
            ) : null}
          </div>
        ) : null}

        {rows.length ? (
          <table className="w-full table-fixed border-collapse text-left">
            <thead className="hidden lg:table-header-group">
              <tr className="text-[13.5px] text-label-3">
                <th scope="col" className="w-[68px] py-4 pl-[26px] font-normal">
                  <input type="checkbox" aria-label="Select all on this page" className={check} checked={allOn} onChange={() => setSelected(allOn ? new Set() : new Set(rows.map((r) => r.id)))} />
                </th>
                <th scope="col" className="w-[25%] py-4 font-normal">Company</th>
                <th scope="col" className="w-[68px] py-4 font-normal">Grade</th>
                <th scope="col" className="w-[118px] py-4 font-normal">Stage</th>
                <th scope="col" className="py-4 font-normal">Why now</th>
                <th scope="col" className="w-[170px] py-4 font-normal">Contact</th>
                <th scope="col" className="w-[92px] py-4 pr-[26px] font-normal">Found</th>
              </tr>
            </thead>
            <tbody ref={tableRef}>
              {rows.map((r, i) => {
                const on = selected.has(r.id)
                const stage = local[r.id] ?? r.stage
                return (
                  <tr
                    key={r.id}
                    data-row
                    aria-selected={on || undefined}
                    className={cx('relative hairline-t align-middle hover:bg-fill-3 lg:h-[90px]', on && 'bg-fill-3', cursor === i && 'bg-fill-3')}
                  >
                    <td className="w-12 py-4 pl-4 align-top lg:pl-[26px] lg:align-middle">
                      <input type="checkbox" aria-label={`Select ${r.name}`} className={cx(check, 'relative z-10')} checked={on} onChange={() => toggle(r.id)} />
                    </td>
                    <td className="py-4 pr-4 lg:pr-3" colSpan={1}>
                      <Link href={`/leads/${r.id}`} className="block font-medium text-label-1 outline-none after:absolute after:inset-0 focus-visible:underline lg:text-[16px]" onFocus={() => setCursor(i)}>
                        {r.name}
                      </Link>
                      <p className="type-subhead mt-0.5 truncate text-label-3 lg:text-[14px]">{r.sub}</p>
                      {/* Phone: the rest of the row in two quiet lines. */}
                      <p className="type-subhead mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-label-2 lg:hidden">
                        <GradeLetter grade={r.grade} className="size-5 text-[11px]" />
                        <span>{stageLabel(stage)}</span>
                        <Status tone={r.contact.tone}>{r.contact.text}</Status>
                      </p>
                      {r.why ? <p className="type-subhead mt-1 line-clamp-2 text-label-2 lg:hidden">{r.why}</p> : null}
                    </td>
                    <td className="hidden py-4 lg:table-cell">
                      <GradeLetter grade={r.grade} />
                    </td>
                    <td className="hidden py-4 text-[15px] text-label-1 lg:table-cell">{stageLabel(stage)}</td>
                    <td className="hidden py-4 pr-6 text-[15px] text-label-2 lg:table-cell">
                      <span className="line-clamp-2">{r.why || <span className="text-label-3">No dated signal yet</span>}</span>
                    </td>
                    <td className="hidden py-4 text-[14px] text-label-2 lg:table-cell">
                      <Status tone={r.contact.tone}>{r.contact.text}</Status>
                    </td>
                    <td className="hidden py-4 pr-[26px] text-[14.5px] text-label-3 lg:table-cell">{r.found}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <EmptyState
            icon={<SearchX />}
            title={scope === 'all' && !filters.q ? 'No leads yet' : 'No leads match'}
            action={
              scope === 'all' && !filters.q ? undefined : (
                <Link href="/leads" className={outlineClass()}>
                  Show all leads
                </Link>
              )
            }
          >
            {scope === 'all' && !filters.q ? 'The engine adds new startups every night. They will appear here in the morning.' : 'Try fewer filters or a shorter search.'}
          </EmptyState>
        )}

        {total > pageSize ? (
          <nav aria-label="Pages" className="flex items-center justify-between gap-3 px-4 py-3 hairline-t lg:px-[26px]">
            <span className="type-subhead text-label-3">
              {formatNumber((page - 1) * pageSize + 1)} to {formatNumber(Math.min(total, page * pageSize))} of {formatNumber(total)}
            </span>
            <div className="flex gap-1">
              <Link aria-disabled={page <= 1 || undefined} href={href({ ...filters, page: page - 1 })} scroll={false} className={plainClass('small')}>
                <ChevronLeft aria-hidden />
                Previous
              </Link>
              <Link aria-disabled={page >= pages || undefined} href={href({ ...filters, page: page + 1 })} scroll={false} className={plainClass('small')}>
                Next
                <ChevronRight aria-hidden />
              </Link>
            </div>
          </nav>
        ) : null}
      </section>
      <p className="type-caption mt-3 hidden text-label-3 lg:block">J and K move, Enter opens, X selects, / searches.</p>

      <ReasonSheet stage={askReason} pending={pending} onCancel={() => setAskReason(null)} onSave={(reason) => askReason && moveSelected(askReason, reason)} />
    </div>
  )
}
