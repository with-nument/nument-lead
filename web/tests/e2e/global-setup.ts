import { createFixtures } from './fixtures'

export default async function globalSetup() {
  const run = await createFixtures()
  console.log(`e2e fixtures ready: run ${run.runId}, 2 test users, ${run.businessIds.length} fixture leads`)
}
