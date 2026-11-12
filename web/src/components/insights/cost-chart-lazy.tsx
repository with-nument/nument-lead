'use client'

import dynamic from 'next/dynamic'
import { Skeleton } from '@/components/ui/skeleton'

/**
 * The spend chart, loaded after the page is interactive: Recharts is the biggest library in the app
 * and only admins see this chart. The placeholder has the chart's height, so nothing moves.
 */
export const CostChart = dynamic(() => import('./cost-chart').then((m) => m.CostChart), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full rounded-xl" />,
})
