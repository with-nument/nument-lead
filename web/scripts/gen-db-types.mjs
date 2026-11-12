// Regenerates src/lib/database.types.ts from the live Supabase project (Management API type generator).
// Needs SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF in the environment. Never prints them.
import { writeFileSync } from 'node:fs'

const token = process.env.SUPABASE_ACCESS_TOKEN
const ref = process.env.SUPABASE_PROJECT_REF
if (!token || !ref) {
  console.error('Set SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF first.')
  process.exit(1)
}
const res = await fetch(`https://api.supabase.com/v1/projects/${ref}/types/typescript?included_schemas=public`, {
  headers: { Authorization: `Bearer ${token}` },
})
if (!res.ok) {
  console.error(`Supabase answered ${res.status}.`)
  process.exit(1)
}
const { types } = await res.json()
const header = [
  '// Database types for the public schema.',
  '// Generated: run `pnpm db:types` (needs SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF) after every migration.',
  '// Do not edit by hand.',
  '',
].join('\n')
writeFileSync('src/lib/database.types.ts', `${header}\n${types.trim()}\n`)
console.log('src/lib/database.types.ts updated')
