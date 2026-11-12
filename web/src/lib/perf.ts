import { appendFileSync } from 'node:fs'

/**
 * Server-side timers for every Supabase call (database, auth, storage). On in `next dev`, or in any
 * build with PERF_LOG=1. Each call prints one `[perf]` line; with PERF_LOG_FILE set it is also appended
 * there as JSON, which `tests/perf` reads to count queries per page. Off in production by default.
 * Never logs headers, bodies or query strings: only the method, the table or endpoint and the time.
 */
export const perfEnabled = process.env.NODE_ENV === 'development' || process.env.PERF_LOG === '1'

export type PerfEntry = { at: number; ms: number; source: string; kind: 'rest' | 'auth' | 'storage' | 'local' | 'other'; name: string; status?: number }

export function perfLog(entry: Omit<PerfEntry, 'at'> & { at?: number }) {
  if (!perfEnabled) return
  const e: PerfEntry = { at: entry.at ?? Date.now(), ...entry } as PerfEntry
  console.log(`[perf] ${e.source} ${e.kind} ${e.name} ${e.ms.toFixed(1)}ms${e.status ? ` ${e.status}` : ''}`)
  const file = process.env.PERF_LOG_FILE
  if (file) {
    try {
      appendFileSync(file, `${JSON.stringify(e)}\n`)
    } catch {
      // Timing is best effort; never break a request over it.
    }
  }
}

function describe(input: RequestInfo | URL): { kind: PerfEntry['kind']; name: string } {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  try {
    const { pathname } = new URL(raw)
    const parts = pathname.split('/').filter(Boolean)
    if (parts[0] === 'rest') return { kind: 'rest', name: parts.slice(2).join('/') || 'root' }
    if (parts[0] === 'auth') return { kind: 'auth', name: parts.slice(2).join('/') || 'root' }
    if (parts[0] === 'storage') return { kind: 'storage', name: parts.slice(2, 4).join('/') }
    return { kind: 'other', name: pathname }
  } catch {
    return { kind: 'other', name: 'unknown' }
  }
}

/** A fetch for Supabase clients that times each call. Undefined when timing is off, so the client keeps its default. */
export function timedFetch(source: string): typeof fetch | undefined {
  if (!perfEnabled) return undefined
  return async (input, init) => {
    const at = Date.now()
    const start = performance.now()
    const { kind, name } = describe(input)
    const method = init?.method ?? (input instanceof Request ? input.method : 'GET')
    try {
      const res = await fetch(input, init)
      perfLog({ at, ms: performance.now() - start, source, kind, name: `${method} ${name}`, status: res.status })
      return res
    } catch (e) {
      perfLog({ at, ms: performance.now() - start, source, kind, name: `${method} ${name} failed` })
      throw e
    }
  }
}

/** Times a local step (for example JWT verification) that makes no network call of its own. */
export async function timed<T>(source: string, name: string, fn: () => Promise<T>): Promise<T> {
  if (!perfEnabled) return fn()
  const at = Date.now()
  const start = performance.now()
  try {
    return await fn()
  } finally {
    perfLog({ at, ms: performance.now() - start, source, kind: 'local', name })
  }
}
