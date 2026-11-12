'use client'

import Link from 'next/link'
import { useState, useTransition } from 'react'
import { BookmarkPlus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { deleteView, saveView } from '@/app/(app)/leads/actions'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Checkbox, Input } from '@/components/ui/input'

export type SavedView = { id: string; name: string; qs: string }

export function SavedViews({ mine, shared, currentQs }: { mine: SavedView[]; shared: SavedView[]; currentQs: string }) {
  const [pending, startTransition] = useTransition()
  if (!mine.length && !shared.length) return null
  const item = (v: SavedView, removable: boolean) => (
    <li key={v.id} className="group flex items-center gap-1">
      <Link
        href={v.qs ? `/leads?${v.qs}` : '/leads'}
        aria-current={v.qs === currentQs ? 'page' : undefined}
        className="min-w-0 flex-1 truncate rounded-lg px-1.5 py-1.5 text-base text-tx-2 hover:bg-surface-2 aria-[current=page]:text-indigo-800"
      >
        {v.name}
      </Link>
      {removable ? (
        <button
          type="button"
          disabled={pending}
          aria-label={`Delete view ${v.name}`}
          onClick={() =>
            startTransition(async () => {
              const r = await deleteView(v.id)
              if (r.ok) toast(r.message ?? 'Deleted')
              else toast.error(r.message)
            })
          }
          className="grid size-7 shrink-0 place-items-center rounded-full text-tx-4 opacity-0 group-hover:opacity-100 hover:bg-surface-2 hover:text-bad focus-visible:opacity-100"
        >
          <Trash2 className="size-3.5" />
        </button>
      ) : null}
    </li>
  )
  return (
    <div className="mt-6 border-t border-line-2 pt-4">
      {mine.length ? (
        <>
          <h3 className="label-mono mb-1">My views</h3>
          <ul>{mine.map((v) => item(v, true))}</ul>
        </>
      ) : null}
      {shared.length ? (
        <>
          <h3 className="label-mono mt-4 mb-1">Shared views</h3>
          <ul>{shared.map((v) => item(v, false))}</ul>
        </>
      ) : null}
    </div>
  )
}

export function SaveViewButton({ currentQs }: { currentQs: string }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="md" data-tour="save-view">
          <BookmarkPlus aria-hidden />
          Save view
        </Button>
      </DialogTrigger>
      <DialogContent title="Save this view" description="Saves the current filters, search and sort so you can open them in one click.">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            startTransition(async () => {
              const r = await saveView({ name, query: currentQs, shared })
              if (r.ok) {
                toast(r.message ?? 'Saved')
                setOpen(false)
                setName('')
                setShared(false)
                setError(null)
              } else setError(r.message)
            })
          }}
        >
          <Field label="Name" error={error}>
            {({ id, describedBy, invalid }) => (
              <Input id={id} value={name} onChange={(e) => setName(e.currentTarget.value)} maxLength={60} required aria-describedby={describedBy} aria-invalid={invalid || undefined} placeholder="Clinics in Pune, grade A" />
            )}
          </Field>
          <label className="flex cursor-pointer items-center gap-2.5 text-base text-tx-2">
            <Checkbox checked={shared} onChange={(e) => setShared(e.currentTarget.checked)} />
            Share with the team
          </label>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={pending}>
              Save view
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
