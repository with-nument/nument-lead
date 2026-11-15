import type { BrowserContext, Page } from '@playwright/test'

// Turning the new design (v2) on and off for a test, the way Settings does it: the nl_ui cookie
// (src/lib/ui-flag.ts). The proxy then serves listed pages from src/app/(v2)/v2 at their normal URLs.

export const UI_COOKIE = 'nl_ui'

export async function useNewDesign(context: BrowserContext, baseURL: string, on = true) {
  if (!on) {
    await context.clearCookies({ name: UI_COOKIE })
    return
  }
  await context.addCookies([{ name: UI_COOKIE, value: '2', url: baseURL, sameSite: 'Lax' }])
}

/**
 * Opaque materials (no blur, no translucency) for stable screenshots and pixel checks. Must run before
 * the page loads; theme.css swaps every material for its solid fallback under html[data-materials=solid].
 */
export async function solidMaterials(page: Page) {
  await page.addInitScript(() => {
    document.documentElement.dataset.materials = 'solid'
  })
}
