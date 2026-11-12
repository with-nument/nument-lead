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

const nextConfig: NextConfig = {
  // Render runs the self-contained server (`node .next/standalone/server.js`).
  output: 'standalone',
  poweredByHeader: false,
  reactStrictMode: true,
  // Cache Components: the shell prerenders, per-user data streams in behind Suspense.
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    serverActions: {
      // Proposal uploads are up to 10 MB, plus multipart overhead.
      bodySizeLimit: '11mb',
      allowedOrigins: [...new Set([appHost, 'leads.nument.in', 'nument-leads-web.onrender.com'].filter((h): h is string => Boolean(h)))],
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
    return [{ source: '/:path*', headers: securityHeaders }]
  },
}

export default nextConfig
