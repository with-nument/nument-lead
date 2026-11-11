'use client'

import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import { formatInr } from '@/lib/format'

type Point = { day: string; label: string; inr: number }

function Tip({ active, payload }: Partial<TooltipContentProps<number, string>>) {
  const p = payload?.[0]?.payload as Point | undefined
  if (!active || !p) return null
  return (
    <div className="shadow-menu rounded-xl border border-line bg-surface px-3 py-2">
      <div className="text-base font-medium text-tx-1">{formatInr(p.inr)}</div>
      <div className="flex items-center gap-1.5 text-xs text-tx-3">
        <span aria-hidden className="inline-block h-0.5 w-3 rounded bg-indigo-600" />
        Spend on {p.label}
      </div>
    </div>
  )
}

/** Spend per day (2px line, 10% wash) against the daily cap, one axis (plan 15.6.7). */
export function CostChart({ data, cap }: { data: Point[]; cap: number }) {
  const top = Math.max(cap * 1.15, ...data.map((d) => d.inr))
  return (
    <div className="h-64 w-full" role="img" aria-label={`Daily spend against the ${formatInr(cap)} cap`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--color-st-secondary)" strokeWidth={1} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={{ stroke: 'var(--color-st)' }}
            tick={{ fill: 'var(--color-tx-tertiary)', fontSize: 12, fontFamily: 'var(--nf-sans)' }}
            minTickGap={24}
          />
          <YAxis
            width={56}
            domain={[0, Math.ceil(top / 100) * 100]}
            tickLine={false}
            axisLine={false}
            tick={{ fill: 'var(--color-tx-tertiary)', fontSize: 12, fontFamily: 'var(--nf-sans)' }}
            tickFormatter={(v: number) => `₹${v.toLocaleString('en-IN')}`}
          />
          <Tooltip content={<Tip />} cursor={{ stroke: 'var(--grey-400)', strokeWidth: 1 }} />
          <ReferenceLine
            y={cap}
            stroke="var(--grey-600)"
            strokeDasharray="4 4"
            label={{ value: `Cap ${formatInr(cap)}`, position: 'insideTopRight', fill: 'var(--color-tx-tertiary)', fontSize: 12 }}
          />
          <Area type="monotone" dataKey="inr" stroke="var(--indigo-600)" strokeWidth={2} fill="var(--indigo-600)" fillOpacity={0.1} activeDot={{ r: 4, stroke: 'var(--color-sf-white)', strokeWidth: 2 }} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
