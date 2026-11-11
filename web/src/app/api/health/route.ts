import { connection } from 'next/server'

/** Render health check. No database call, so a Supabase hiccup never restarts the web service. */
export async function GET() {
  await connection()
  return Response.json(
    { ok: true, env: process.env.APP_ENV ?? 'dev', at: new Date().toISOString() },
    { headers: { 'Cache-Control': 'no-store' } },
  )
}
