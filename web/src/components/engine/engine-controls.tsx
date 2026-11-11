'use client'

import { useActionState, useState, useTransition } from 'react'
import { Play } from 'lucide-react'
import { toast } from 'sonner'
import { addCustomQuery, saveBudget, setSegmentEnabled, setSegmentQuota, setSourceEnabled, triggerRun } from '@/app/(app)/engine/actions'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Checkbox, Input, Select, Textarea } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import { Switch } from '@/components/ui/switch'
import type { ActionResult } from '@/lib/action-result'

function useToastAction() {
  const [pending, start] = useTransition()
  const run = (fn: () => Promise<ActionResult>, onFail?: () => void) =>
    start(async () => {
      const r = await fn()
      if (r.ok) toast(r.message ?? 'Saved')
      else {
        toast.error(r.message)
        onFail?.()
      }
    })
  return { pending, run }
}

export function SegmentToggle({ id, label, enabled }: { id: string; label: string; enabled: boolean }) {
  const { pending, run } = useToastAction()
  const [on, setOn] = useState(enabled)
  return (
    <Switch
      label={`${label} on or off`}
      checked={on}
      disabled={pending}
      onCheckedChange={(v) => {
        setOn(v)
        run(() => setSegmentEnabled({ id, enabled: v }), () => setOn(!v))
      }}
    />
  )
}

export function QuotaInput({ id, label, quota }: { id: string; label: string; quota: number }) {
  const { pending, run } = useToastAction()
  const [value, setValue] = useState(String(quota))
  const save = () => {
    if (value === String(quota)) return
    run(() => setSegmentQuota({ id, quota: Number(value) }), () => setValue(String(quota)))
  }
  return (
    <Input
      aria-label={`Daily quota for ${label}`}
      inputMode="numeric"
      className="h-9 w-24 text-right tabular"
      value={value}
      disabled={pending}
      onChange={(e) => setValue(e.currentTarget.value.replace(/\D/g, ''))}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
      }}
    />
  )
}

export function SourceToggle({ source, enabled }: { source: string; enabled: boolean }) {
  const { pending, run } = useToastAction()
  const [on, setOn] = useState(enabled)
  return (
    <Switch
      label={`${source} on or off`}
      checked={on}
      disabled={pending}
      onCheckedChange={(v) => {
        setOn(v)
        run(() => setSourceEnabled({ source, enabled: v }), () => setOn(!v))
      }}
    />
  )
}

export function BudgetForm({ budget }: { budget: { daily_cap_inr: number; alert_pct: number; research_per_day: number } }) {
  const [state, action] = useActionState<ActionResult | undefined, FormData>(async (prev, fd) => {
    const r = await saveBudget(prev, fd)
    if (r.ok) toast(r.message ?? 'Saved')
    return r
  }, undefined)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-3">
      <Field label="Daily cap (₹)" error={errors?.daily_cap_inr}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="daily_cap_inr" inputMode="decimal" defaultValue={budget.daily_cap_inr} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Alert at (%)" error={errors?.alert_pct}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="alert_pct" inputMode="numeric" defaultValue={budget.alert_pct} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <Field label="Research per day" error={errors?.research_per_day}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} name="research_per_day" inputMode="numeric" defaultValue={budget.research_per_day} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <div className="sm:col-span-3">
        <SubmitButton size="md">Save budget</SubmitButton>
      </div>
    </form>
  )
}

export function RunNow({ segments, configured }: { segments: { id: string; label: string }[]; configured: boolean }) {
  const { pending, run } = useToastAction()
  const [dryRun, setDryRun] = useState(true)
  const [limit, setLimit] = useState('')
  const [segment, setSegment] = useState('')
  const start = (kind: 'night' | 'morning' | 'sheet') => run(() => triggerRun({ kind, dryRun, limit, segment }))
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex h-10 cursor-pointer items-center gap-2 text-base text-tx-2">
          <Checkbox checked={dryRun} onChange={(e) => setDryRun(e.currentTarget.checked)} />
          Dry run (nothing is written)
        </label>
        <div className="w-28">
          <label htmlFor="run-limit" className="mb-1 block text-sm text-tx-3">
            Limit
          </label>
          <Input id="run-limit" inputMode="numeric" placeholder="All" value={limit} onChange={(e) => setLimit(e.currentTarget.value.replace(/\D/g, ''))} />
        </div>
        <div className="w-52">
          <label htmlFor="run-segment" className="mb-1 block text-sm text-tx-3">
            Segment
          </label>
          <Select id="run-segment" value={segment} onChange={(e) => setSegment(e.currentTarget.value)}>
            <option value="">All segments</option>
            {segments.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={pending || !configured} onClick={() => start('night')}>
          <Play aria-hidden />
          Run night
        </Button>
        <Button variant="secondary" disabled={pending || !configured} onClick={() => start('morning')}>
          Run morning
        </Button>
        <Button variant="secondary" disabled={pending || !configured} onClick={() => start('sheet')}>
          Sync sheet
        </Button>
      </div>
      {!configured ? <p className="text-sm text-tx-3">Runs start from GitHub Actions. Set GH_REPO and GH_DISPATCH_TOKEN on the server to turn these on.</p> : null}
    </div>
  )
}

export function CustomQueryForm({ segments }: { segments: { id: string; label: string }[] }) {
  const [state, action] = useActionState<ActionResult | undefined, FormData>(async (prev, fd) => {
    const r = await addCustomQuery(prev, fd)
    if (r.ok) toast(r.message ?? 'Saved')
    return r
  }, undefined)
  const errors = state && !state.ok ? state.fieldErrors : undefined
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-[200px_minmax(0,1fr)_auto] sm:items-end">
      <Field label="Segment" error={errors?.segmentId}>
        {({ id }) => (
          <Select id={id} name="segmentId" defaultValue={segments[0]?.id}>
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
          <Textarea id={id} name="query" rows={1} className="min-h-10 py-2" placeholder="Dental chains in Dubai with 3 or more branches" aria-describedby={describedBy} aria-invalid={invalid || undefined} />
        )}
      </Field>
      <SubmitButton>Add</SubmitButton>
    </form>
  )
}
