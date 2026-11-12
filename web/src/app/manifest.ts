import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Nument Leads',
    short_name: 'Leads',
    description: 'Daily, evidence-backed leads for the Nument team.',
    start_url: '/',
    display: 'standalone',
    background_color: '#fcfcfc',
    theme_color: '#2e2f9e',
    icons: [
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
  }
}
