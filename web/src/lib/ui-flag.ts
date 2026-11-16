/**
 * The new design (v2) rollout switch. Pure and edge-safe: the proxy, server and client all import it.
 *
 * A person opts in from Settings ("Try the new design"), which sets the `nl_ui=2` cookie. For every page
 * listed in V2_ROUTES the proxy then serves the v2 screen from `src/app/(v2)/v2/...` while the address bar
 * keeps the normal URL (a rewrite, not a redirect). Pages not listed keep the current design, so the
 * redesign ships one page at a time. A page joins the list once its v2 screen is complete.
 */

export const UI_COOKIE = 'nl_ui'
export const UI_V2 = '2'
/** Where the v2 screens live in the app directory. Links always use the normal URL, never this prefix. */
export const V2_PREFIX = '/v2'

/**
 * Pages that have a v2 screen. An entry is an exact path, `/path/*` for the path and everything under it, or a
 * path with `:uuid` segments, each matching one UUID (so '/leads/:uuid' is a lead page but never
 * '/leads/export', the CSV download). '/calls' and '/deals' are new destinations with no current-design page.
 */
export const V2_ROUTES: readonly string[] = [
  '/', '/calls', '/deals', '/leads', '/leads/:uuid', '/inbox', '/settings', '/engine', '/insights',
]

const ONE_YEAR = 60 * 60 * 24 * 365

function normalize(pathname: string): string {
  const path = pathname.replace(/\/{2,}/g, '/')
  return path.length > 1 ? path.replace(/\/+$/, '') : path || '/'
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function matches(route: string, path: string): boolean {
  if (route.endsWith('/*')) {
    const base = route.slice(0, -2)
    return path === base || path.startsWith(`${base}/`)
  }
  if (route.includes(':uuid')) {
    const want = route.split('/')
    const got = path.split('/')
    return want.length === got.length && want.every((seg, i) => (seg === ':uuid' ? UUID.test(got[i] ?? '') : seg === got[i]))
  }
  return path === route
}

/** The v2 path to render for a normal URL path, or null when that page has no v2 screen yet. */
export function v2PathFor(pathname: string, routes: readonly string[] = V2_ROUTES): string | null {
  const path = normalize(pathname)
  if (path === V2_PREFIX || path.startsWith(`${V2_PREFIX}/`)) return null
  if (!routes.some((r) => matches(r, path))) return null
  return path === '/' ? V2_PREFIX : `${V2_PREFIX}${path}`
}

/** The normal URL path for a v2 path ('/v2/calls' is '/calls'); other paths come back unchanged. */
export function canonicalPath(pathname: string): string {
  const path = normalize(pathname)
  if (path === V2_PREFIX) return '/'
  return path.startsWith(`${V2_PREFIX}/`) ? path.slice(V2_PREFIX.length) : path
}

/** True when the cookie value turns the new design on. */
export const isV2 = (value: string | undefined | null) => value === UI_V2

/** A `document.cookie` string that turns the new design on or off for this browser. */
export function uiCookie(on: boolean, secure: boolean): string {
  const parts = on ? [`${UI_COOKIE}=${UI_V2}`, 'Path=/', `Max-Age=${ONE_YEAR}`, 'SameSite=Lax'] : [`${UI_COOKIE}=`, 'Path=/', 'Max-Age=0', 'SameSite=Lax']
  if (secure) parts.push('Secure')
  return parts.join('; ')
}

/**
 * Browser only: switches the design and reloads, so no page from the other design stays in the
 * client cache. Turning it on opens Today, the first v2 screen; turning it off stays on the page.
 */
export function switchDesign(on: boolean) {
  document.cookie = uiCookie(on, window.location.protocol === 'https:')
  // A full page load on purpose: client-side navigation could reuse pages cached in the other design.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  if (on) window.location.assign('/')
  else window.location.reload()
}
