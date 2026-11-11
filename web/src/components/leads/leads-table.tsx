'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState, useTransition } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type VisibilityState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3, Download, X } from 'lucide-react'
import { toast } from 'sonner'
import { bulkAssignOwner, bulkSuppress, bulkUpdateStage } from '@/app/(app)/leads/actions'
import { GradeBadge, StageBadge, Tag } from '@/components/ui/badge'
import { Button, buttonClasses } from '@/components/ui/button'
import { Menu, MenuContent, MenuLabel, MenuTrigger } from '@/components/ui/dropdown-menu'
import { Checkbox } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { formatInr } from '@/lib/format'
import { filtersToQuery, type LeadFilters, type SortKey } from '@/lib/leads-filters'
import { STAGES } from '@/lib/stages'
import { useFilterNav } from './use-filter-nav'

/** One row as the table shows it. Dates and ages are formatted on the server (India time). */
export type LeadRowView = {
  id: string
  name: string
  host: string
  segment: string
  country: string
  city: string
  grade: string | null
  stage: string
  signal: string
  signalAge: string
  signalUrl: string | null
  score: number | null
  pitch: string
  phoneType: string
  owner: string
  activity: string
  due: string
  dueState: 'none' | 'overdue' | 'today' | 'later'
  deal?: number | null
}

const SORTABLE: Partial<Record<string, SortKey>> = {
  name: 'company',
  grade: 'grade',
  stage: 'stage',
  score: 'score',
  activity: 'activity',
  due: 'due',
}

const STORAGE_KEY = 'nument.leads.columns.v1'
const DEFAULT_HIDDEN: VisibilityState = { country: false, pitch: false, phoneType: false }

export function LeadsTable({
  rows,
  filters,
  canEdit,
  isAdmin,
  team,
}: {
  rows: LeadRowView[]
  filters: LeadFilters
  canEdit: boolean
  isAdmin: boolean
  team: { id: string; name: string }[]
}) {
  const { go, pending } = useFilterNav(filters)
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [visibility, setVisibility] = useState<VisibilityState>(DEFAULT_HIDDEN)

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY)
      if (saved) setVisibility(JSON.parse(saved) as VisibilityState)
    } catch {
      // Private mode or blocked storage: keep the defaults.
    }
  }, [])

  const changeVisibility = (next: VisibilityState) => {
    setVisibility(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Not saved; the choice still applies until the page reloads.
    }
  }

  const columns = useMemo<ColumnDef<LeadRowView>[]>(() => {
    const cols: ColumnDef<LeadRowView>[] = []
    if (canEdit) {
      cols.push({
        id: 'select',
        enableHiding: false,
        header: ({ table }) => (
          <Checkbox
            aria-label="Select all leads on this page"
            checked={table.getIsAllRowsSelected()}
            ref={(el: HTMLInputElement | null) => {
              if (el) el.indeterminate = table.getIsSomeRowsSelected()
            }}
            onChange={table.getToggleAllRowsSelectedHandler()}
          />
        ),
        cell: ({ row }) => (
          <Checkbox aria-label={`Select ${row.original.name}`} checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} />
        ),
      })
    }
    cols.push(
      { id: 'grade', header: 'Grade', enableHiding: false, cell: ({ row }) => <GradeBadge grade={row.original.grade} /> },
      {
        id: 'name',
        header: 'Company',
        enableHiding: false,
        cell: ({ row }) => (
          <div className="max-w-[260px] min-w-[180px]">
            <Link href={`/leads/${row.original.id}`} prefetch className="block truncate font-medium text-tx-1 hover:text-indigo-800">
              {row.original.name}
            </Link>
            {row.original.host ? <div className="truncate text-xs text-tx-3">{row.original.host}</div> : null}
          </div>
        ),
      },
      { id: 'segment', header: 'Segment', cell: ({ row }) => <span className="whitespace-nowrap text-tx-2">{row.original.segment}</span> },
      { id: 'country', header: 'Country', cell: ({ row }) => <span className="text-tx-2">{row.original.country}</span> },
      { id: 'city', header: 'City', cell: ({ row }) => <span className="whitespace-nowrap text-tx-2">{row.original.city}</span> },
      { id: 'stage', header: 'Stage', enableHiding: false, cell: ({ row }) => <StageBadge stage={row.original.stage} /> },
      {
        id: 'signal',
        header: 'Top signal',
        cell: ({ row }) =>
          row.original.signal ? (
            <div className="max-w-[220px] min-w-[150px]">
              <div className="truncate text-tx-2">{row.original.signal}</div>
              <div className="text-xs text-tx-3">{row.original.signalAge}</div>
            </div>
          ) : (
            <span className="text-tx-4">None live</span>
          ),
      },
      { id: 'score', header: 'Score', cell: ({ row }) => <span className="tabular text-tx-2">{row.original.score ?? ''}</span> },
      { id: 'pitch', header: 'Pitch mode', cell: ({ row }) => <span className="whitespace-nowrap text-tx-2">{row.original.pitch}</span> },
      { id: 'phoneType', header: 'Phone', cell: ({ row }) => <span className="text-tx-2">{row.original.phoneType}</span> },
      { id: 'owner', header: 'Owner', cell: ({ row }) => <span className="whitespace-nowrap text-tx-2">{row.original.owner}</span> },
      { id: 'activity', header: 'Last activity', cell: ({ row }) => <span className="whitespace-nowrap text-tx-3">{row.original.activity}</span> },
      {
        id: 'due',
        header: 'Due',
        cell: ({ row }) =>
          row.original.dueState === 'overdue' ? (
            <Tag tone="bad">Overdue, {row.original.due}</Tag>
          ) : (
            <span className={cn('whitespace-nowrap', row.original.dueState === 'today' ? 'text-tx-1' : 'text-tx-3')}>{row.original.due}</span>
          ),
      },
    )
    if (isAdmin) {
      cols.push({
        id: 'deal',
        header: 'Deal value',
        cell: ({ row }) => <span className="tabular whitespace-nowrap text-green-800">{row.original.deal ? formatInr(row.original.deal) : ''}</span>,
      })
    }
    return cols
  }, [canEdit, isAdmin])

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table returns new functions each render by design
  const table = useReactTable({
    data: rows,
    columns,
    state: { rowSelection: selection, columnVisibility: visibility },
    getRowId: (r) => r.id,
    onRowSelectionChange: setSelection,
    onColumnVisibilityChange: (updater) => changeVisibility(typeof updater === 'function' ? updater(visibility) : updater),
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    enableRowSelection: canEdit,
  })

  const selectedIds = Object.keys(selection).filter((k) => selection[k])

  const sortHeader = (id: string, label: React.ReactNode) => {
    const key = SORTABLE[id]
    if (!key) return label
    const active = filters.sort === key
    const nextDir = active && filters.dir === 'desc' ? 'asc' : 'desc'
    const Icon = !active ? ArrowUpDown : filters.dir === 'desc' ? ArrowDown : ArrowUp
    return (
      <button
        type="button"
        onClick={() => go({ sort: key, dir: nextDir })}
        className={cn('-mx-1 inline-flex items-center gap-1 rounded px-1 uppercase hover:text-tx-1', active && 'text-tx-1')}
        aria-label={`Sort by ${String(label)}`}
      >
        {label}
        <Icon aria-hidden className={cn('size-3', !active && 'opacity-40')} />
      </button>
    )
  }

  return (
    <div className={cn('transition-opacity', pending && 'opacity-60')}>
      <div className="flex items-center justify-end gap-2 px-4 py-2 sm:px-5">
        <Menu>
          <MenuTrigger asChild>
            <Button size="sm" variant="ghost">
              <Columns3 aria-hidden />
              Columns
            </Button>
          </MenuTrigger>
          <MenuContent>
            <MenuLabel>Show columns</MenuLabel>
            {table
              .getAllLeafColumns()
              .filter((c) => c.getCanHide())
              .map((c) => (
                <label key={c.id} className="flex h-9 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 text-base hover:bg-surface-2">
                  <Checkbox checked={c.getIsVisible()} onChange={c.getToggleVisibilityHandler()} />
                  {String(c.columnDef.header)}
                </label>
              ))}
          </MenuContent>
        </Menu>
      </div>

      {/* Desktop and tablet: the table. Phones: stacked cards below. */}
      <div className="hidden max-h-[72dvh] overflow-auto border-t border-line-2 sm:block">
        <table className="w-full text-left text-base">
          <thead className="sticky top-0 z-10 bg-surface">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    scope="col"
                    aria-sort={
                      SORTABLE[h.column.id] && filters.sort === SORTABLE[h.column.id]
                        ? filters.dir === 'asc'
                          ? 'ascending'
                          : 'descending'
                        : undefined
                    }
                    className="label-mono h-10 border-b border-line-2 px-3 font-normal whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5"
                  >
                    {h.isPlaceholder ? null : sortHeader(h.column.id, flexRender(h.column.columnDef.header, h.getContext()) as React.ReactNode)}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={cn('border-b border-line-2 last:border-b-0 hover:bg-grey-50', row.getIsSelected() && 'bg-indigo-50')}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="h-11 px-3 align-middle first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="divide-y divide-line-2 border-t border-line-2 sm:hidden">
        {rows.map((r) => (
          <li key={r.id} className="px-4 py-3">
            <div className="flex items-start gap-3">
              <GradeBadge grade={r.grade} className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <Link href={`/leads/${r.id}`} className="block truncate font-medium text-tx-1">
                  {r.name}
                </Link>
                <div className="mt-0.5 truncate text-sm text-tx-3">{[r.city, r.segment].filter(Boolean).join(' · ')}</div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <StageBadge stage={r.stage} />
                  {r.signal ? <span className="text-sm text-tx-2">{r.signal}</span> : null}
                  {r.dueState === 'overdue' ? <Tag tone="bad">Overdue</Tag> : null}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {canEdit && selectedIds.length ? (
        <BulkBar ids={selectedIds} isAdmin={isAdmin} team={team} filters={filters} onDone={() => setSelection({})} />
      ) : null}
    </div>
  )
}

function BulkBar({
  ids,
  isAdmin,
  team,
  filters,
  onDone,
}: {
  ids: string[]
  isAdmin: boolean
  team: { id: string; name: string }[]
  filters: LeadFilters
  onDone: () => void
}) {
  const [stage, setStage] = useState('')
  const [owner, setOwner] = useState('')
  const [pending, startTransition] = useTransition()

  const run = (fn: () => Promise<{ ok: boolean; message?: string }>) =>
    startTransition(async () => {
      const r = await fn()
      if (r.ok) {
        toast(r.message ?? 'Saved')
        onDone()
      } else toast.error(r.message ?? 'Could not save. Try again.')
    })

  const exportHref = `/leads/export?${filtersToQuery(filters)}${filtersToQuery(filters) ? '&' : ''}${ids.map((id) => `ids=${id}`).join('&')}`
  const select = 'h-8 rounded-full border border-line bg-surface px-3 text-sm focus-visible:outline-none focus-visible:focus-ring'

  return (
    <div role="region" aria-label="Bulk actions" className="shadow-menu animate-pop-in fixed inset-x-4 bottom-4 z-40 mx-auto flex max-w-3xl flex-wrap items-center gap-2 rounded-2xl border border-line bg-surface px-4 py-3">
      <span className="mr-1 text-base font-medium text-tx-1">{ids.length} selected</span>
      <label className="sr-only" htmlFor="bulk-stage">
        New stage
      </label>
      <select id="bulk-stage" value={stage} onChange={(e) => setStage(e.currentTarget.value)} className={select}>
        <option value="">Change stage…</option>
        {STAGES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <Button size="sm" variant="primary" disabled={!stage || pending} onClick={() => run(() => bulkUpdateStage({ ids, stage }))}>
        Apply
      </Button>
      {isAdmin ? (
        <>
          <label className="sr-only" htmlFor="bulk-owner">
            Owner
          </label>
          <select id="bulk-owner" value={owner} onChange={(e) => setOwner(e.currentTarget.value)} className={select}>
            <option value="">Assign owner…</option>
            <option value="none">Nobody</option>
            {team.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
          <Button size="sm" variant="secondary" disabled={!owner || pending} onClick={() => run(() => bulkAssignOwner({ ids, ownerId: owner === 'none' ? null : owner }))}>
            Assign
          </Button>
          <Button size="sm" variant="danger" disabled={pending} onClick={() => run(() => bulkSuppress({ ids }))}>
            Do not contact
          </Button>
        </>
      ) : null}
      <a href={exportHref} className={buttonClasses('ghost', 'sm')} download>
        <Download aria-hidden />
        Export
      </a>
      <Button size="icon-sm" variant="ghost" className="ml-auto" aria-label="Clear selection" onClick={onDone}>
        <X />
      </Button>
    </div>
  )
}
