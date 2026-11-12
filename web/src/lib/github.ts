import 'server-only'
import { env } from '@/lib/env'

export const WORKFLOWS = { night: 'night.yml', morning: 'morning.yml', sheet: 'sheet-sync.yml' } as const
export type WorkflowKind = keyof typeof WORKFLOWS

export type DispatchOptions = { dryRun: boolean; limit?: number; segment?: string }

/** Starts an engine workflow on GitHub Actions (workflow_dispatch). The token never leaves the server. */
export async function dispatchWorkflow(kind: WorkflowKind, opts: DispatchOptions): Promise<{ ok: boolean; status: number }> {
  const { GH_REPO, GH_DISPATCH_TOKEN, GH_DISPATCH_REF } = env()
  if (!GH_REPO || !GH_DISPATCH_TOKEN) return { ok: false, status: 0 }
  const res = await fetch(`https://api.github.com/repos/${GH_REPO}/actions/workflows/${WORKFLOWS[kind]}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${GH_DISPATCH_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      'User-Agent': 'nument-leads-web',
    },
    body: JSON.stringify({
      ref: GH_DISPATCH_REF,
      inputs: { dry_run: String(opts.dryRun), limit: opts.limit ? String(opts.limit) : '', segment: opts.segment ?? '' },
    }),
    cache: 'no-store',
  })
  return { ok: res.status === 204 || res.status === 200, status: res.status }
}

export const isDispatchConfigured = () => {
  const { GH_REPO, GH_DISPATCH_TOKEN } = env()
  return Boolean(GH_REPO && GH_DISPATCH_TOKEN)
}
