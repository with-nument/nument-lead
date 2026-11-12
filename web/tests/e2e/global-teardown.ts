import { deleteFixtures, leftovers, removeRunFile } from './fixtures'

export default async function globalTeardown() {
  await deleteFixtures()
  removeRunFile()
  const left = await leftovers()
  const remaining = Object.entries(left).filter(([, n]) => n > 0)
  if (remaining.length) {
    throw new Error(`e2e cleanup left rows behind: ${remaining.map(([k, n]) => `${k}=${n}`).join(', ')}`)
  }
  console.log(`e2e cleanup verified: ${Object.entries(left).map(([k, n]) => `${k}=${n}`).join(', ')}`)
}
