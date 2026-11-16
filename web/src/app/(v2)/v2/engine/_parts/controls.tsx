'use client'

import { useState } from 'react'
import { Pencil, Play, Plus } from 'lucide-react'
import { addCustomQuery, saveBudget, setSegmentEnabled, setSegmentQuota, setSourceEnabled, triggerRun } from '@/app/(app)/engine/actions'
import { addInboxPost } from '@/app/(app)/inbox/actions'
import { Field, FormError, inputClass, Submit, textareaClass } from '@/app/(v2)/v2/_parts/form'
import { useFormAction, useRun } from '@/app/(v2)/v2/_parts/run'
import { Switch } from '@/app/(v2)/v2/_parts/switch'
import { Button } from '@/components/ui2/button'
import { Choice } from '@/app/(v2)/v2/_parts/choice'
import { Select } from '@/components/ui2/select'
import { Sheet, SheetContent } from '@/components/ui2/sheet'

type Opt = { id: string; label: string }

const KINDS = [
  { value: 'morning', label: 'Morning' },
  { value: 'night', label: 'Night' },
  { value: 'sheet', label: 'Sheet sync' },
] as const
type Kind = (typeof KINDS)[number]['value']
const KIND_HINT: Record<Kind, string> = {
  morning: 'Writes messages for the leads found overnight and builds the send list.',
  night: 'Finds and researches new businesses. The long one.',
  sheet: "Copies the leads to the founder's Google Sheet.",
}

/** The page's one solid button: starts an engine run on GitHub Actions, from a sheet with the options. */
export function RunNowButton({ segments, configured }: { segments: Opt[]; configured: boolean }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<Kind>('morning')
  const [dryRun, setDryRun] = useState(true)
  const [limit, setLimit] = useState('')
  const [segment, setSegment] = useState('')
  const [pending, run] = useRun()
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Play aria-hidden />
        Run now
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Run now" description="Starts the engine on GitHub Actions. A dry run checks everything and writes nothing.">
          <div className="flex flex-col gap-5">
            <Choice items={KINDS} value={kind} onValueChange={setKind} label="Which run" />
            <p className="type-subhead -mt-2 text-label-3">{KIND_HINT[kind]}</p>
            <div className="flex items-center justify-between gap-4">
              <span className="text-label-1">Dry run</span>
              <Switch label="Dry run" checked={dryRun} onCheckedChange={setDryRun} />
            </div>
            <Field label="Limit" hint="Leave empty for the usual amount.">
              {({ id, describedBy }) => (
                <input id={id} inputMode="numeric" placeholder="All" value={limit} onChange={(e) => setLimit(e.currentTarget.value.replace(/\D/g, ''))} className={inputClass} aria-describedby={describedBy} />
              )}
            </Field>
            <Field label="Segment">
              {({ id }) => (
                <Select id={id} value={segment} onChange={(e) => setSegment(e.currentTarget.value)} className="w-full">
                  <option value="">All segments</option>
                  {segments.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {!configured ? <p className="type-subhead text-label-3">Runs start from GitHub Actions. Set GH_REPO and GH_DISPATCH_TOKEN on the server to turn this on.</p> : null}
            <div>
              <Button variant="primary" disabled={pending || !configured} aria-busy={pending || undefined} onClick={() => run(() => triggerRun({ kind, dryRun, limit, segment }), { onOk: () => setOpen(false) })}>
                {dryRun ? 'Start dry run' : 'Start run'}
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}

export function BudgetEditButton({ budget }: { budget: { daily_cap_inr: number; alert_pct: number; research_per_day: number } }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        <Pencil aria-hidden />
        Edit
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Budget" description="The engine stops spending for the day at the cap, and emails an alert before it.">
          <BudgetForm budget={budget} onDone={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    </>
  )
}

function BudgetForm({ budget, onDone }: { budget: { daily_cap_inr: number; alert_pct: number; research_per_day: number }; onDone: () => void }) {
  const [state, action, pending] = useFormAction(saveBudget, onDone)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  const field = (name: keyof typeof budget, label: string, mode: 'decimal' | 'numeric', hint?: string) => (
    <Field label={label} hint={hint} error={errors?.[name]}>
      {({ id, describedBy, invalid }) => (
        <input id={id} name={name} inputMode={mode} defaultValue={budget[name]} className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
      )}
    </Field>
  )
  return (
    <form action={action} className="flex flex-col gap-4" noValidate>
      {field('daily_cap_inr', 'Daily cap (₹)', 'decimal')}
      {field('alert_pct', 'Alert at (% of the cap)', 'numeric')}
      {field('research_per_day', 'Businesses researched per day', 'numeric')}
      <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
      <div>
        <Submit pending={pending}>Save budget</Submit>
      </div>
    </form>
  )
}

export function SegmentSwitch({ id, label, enabled }: { id: string; label: string; enabled: boolean }) {
  const [on, setOn] = useState(enabled)
  const [pending, run] = useRun()
  return (
    <Switch
      label={`${label} on or off`}
      checked={on}
      disabled={pending}
      onCheckedChange={(v) => {
        setOn(v)
        run(() => setSegmentEnabled({ id, enabled: v }), { onFail: () => setOn(!v) })
      }}
    />
  )
}

/** The daily quota, saved when the field loses focus (or on Enter). */
export function QuotaInput({ id, label, quota }: { id: string; label: string; quota: number }) {
  const [value, setValue] = useState(String(quota))
  const [saved, setSaved] = useState(String(quota))
  const [pending, run] = useRun()
  return (
    <input
      aria-label={`Daily quota for ${label}`}
      inputMode="numeric"
      value={value}
      disabled={pending}
      onChange={(e) => setValue(e.currentTarget.value.replace(/\D/g, ''))}
      onBlur={() => {
        if (value === saved || value === '') return setValue(saved)
        const before = saved
        setSaved(value)
        run(() => setSegmentQuota({ id, quota: Number(value) }), {
          onFail: () => {
            setSaved(before)
            setValue(before)
          },
        })
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
      }}
      className="h-9 w-16 rounded-control bg-fill-1 px-2 text-right text-[15px] text-label-1 tabular-nums outline-none focus-visible:shadow-[inset_0_0_0_1.5px_var(--ui-label-1)] lg:h-8 lg:text-[14px]"
    />
  )
}

export function SourceSwitch({ source, enabled }: { source: string; enabled: boolean }) {
  const [on, setOn] = useState(enabled)
  const [pending, run] = useRun()
  return (
    <Switch
      label={`${source} on or off`}
      checked={on}
      disabled={pending}
      onCheckedChange={(v) => {
        setOn(v)
        run(() => setSourceEnabled({ source, enabled: v }), { onFail: () => setOn(!v) })
      }}
    />
  )
}

/** Posts: paste a public post someone wrote asking for help. The engine never opens the link itself. */
export function AddPostButton({ segments }: { segments: Opt[] }) {
  const [open, setOpen] = useState(false)
  const [state, action, pending] = useFormAction(addInboxPost, () => setOpen(false))
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        <Plus aria-hidden />
        Paste a post
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Paste a public post" description="Copy the text of a LinkedIn or X post where someone asks for help. The next night run looks the business up on allowed sources.">
          <form action={action} className="flex flex-col gap-4" noValidate>
            <Field label="Post text" error={errors?.text}>
              {({ id, describedBy, invalid }) => (
                <textarea id={id} name="text" rows={6} required className={textareaClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
              )}
            </Field>
            <Field label="Link" hint="Optional. Kept for your reference only." error={errors?.url}>
              {({ id, describedBy, invalid }) => (
                <input id={id} name="url" type="url" inputMode="url" placeholder="https://" autoComplete="off" className={inputClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
              )}
            </Field>
            <Field label="Segment" error={errors?.segmentId}>
              {({ id }) => (
                <Select id={id} name="segmentId" defaultValue="" className="w-full">
                  <option value="">Let the engine decide</option>
                  {segments.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
            <div>
              <Submit pending={pending}>Add post</Submit>
            </div>
          </form>
        </SheetContent>
      </Sheet>
    </>
  )
}

export function AddQueryButton({ segments }: { segments: Opt[] }) {
  const [open, setOpen] = useState(false)
  const [state, action, pending] = useFormAction(addCustomQuery, () => setOpen(false))
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)} disabled={!segments.length}>
        <Plus aria-hidden />
        Add
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Ask the night run" description="Something specific to look for tonight.">
          <form action={action} className="flex flex-col gap-4" noValidate>
            <Field label="Segment" error={errors?.segmentId}>
              {({ id }) => (
                <Select id={id} name="segmentId" defaultValue={segments[0]?.id} className="w-full">
                  {segments.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="What to look for" error={errors?.query}>
              {({ id, describedBy, invalid }) => (
                <textarea id={id} name="query" rows={3} placeholder="Dental chains in Dubai with 3 or more branches" className={textareaClass} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
              )}
            </Field>
            <FormError message={state && !state.ok && !state.fieldErrors ? state.message : undefined} />
            <div>
              <Submit pending={pending}>Add to tonight</Submit>
            </div>
          </form>
        </SheetContent>
      </Sheet>
    </>
  )
}
