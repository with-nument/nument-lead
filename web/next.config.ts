import type { NextConfig } from 'next'

const appHost = (() => {
  try {
    return process.env.NEXT_PUBLIC_APP_URL ? new URL(process.env.NEXT_PUBLIC_APP_URL).host : null
  } catch {
    return null
  }
})()

const securityHeaders = [
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), browsing-topics=()' },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
]

const publicFileCache = [{ key: 'Cache-Control', value: 'public, max-age=86400, stale-while-revalidate=604800' }]

const nextConfig: NextConfig = {
  // Render runs the self-contained server (`node .next/standalone/server.js`).
  output: 'standalone',
  poweredByHeader: false,
  reactStrictMode: true,
  // Cache Components: the shell prerenders, per-user data streams in behind Suspense.
  cacheComponents: true,
  // Links prefetch each page's prerendered shell (skeletons) when they scroll into view. The sidebar and tab
  // bar links (unstable_dynamicOnHover) also fetch the page's data when hovered or touched, so the click
  // shows the finished page at once. Partial Prefetching would turn that hover prefetch back into a
  // shell-only one, so it stays off.
  partialPrefetching: false,
  experimental: {
    // A hover prefetch (data included) is reused for at most 30 s (the minimum; default 5 min), so a page
    // opened from the sidebar is never older than that. Server Actions that change data clear it anyway.
    staleTimes: { static: 30 },
    serverActions: {
      // Proposal uploads are up to 10 MB, plus multipart overhead.
      bodySizeLimit: '11mb',
      allowedOrigins: [
        ...new Set(
          [appHost, 'lead.nument.in', 'leads.nument.in', 'nument-leads-web.onrender.com'].filter((h): h is string => Boolean(h)),
        ),
      ],
    },
    proxyClientMaxBodySize: '11mb',
  },
  turbopack: {
    rules: {
      '*.css': {
        loaders: ['@tailwindcss/turbopack'],
        as: '*.css',
      },
    },
  },
  async headers() {
    return [
      { source: '/:path*', headers: securityHeaders },
      // Files in public/ keep their names when they change, so a day in the browser and a week of serving the
      // old copy while the new one loads, instead of a request on every visit. /_next/static is already
      // cached for a year (immutable) by Next.js, since its file names change with their content.
      { source: '/auth/:file*', headers: publicFileCache },
      { source: '/icon-:size.png', headers: publicFileCache },
    ]
  },
}

export default nextConfig
