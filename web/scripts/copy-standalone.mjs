// Next's standalone server does not include static assets. Copy them next to server.js (plan 15.11.1).
import { cpSync, existsSync } from 'node:fs'

if (!existsSync('.next/standalone')) {
  console.error('No .next/standalone folder. Is output: "standalone" set in next.config.ts?')
  process.exit(1)
}
cpSync('.next/static', '.next/standalone/.next/static', { recursive: true })
if (existsSync('public')) cpSync('public', '.next/standalone/public', { recursive: true })
console.log('standalone assets copied')
